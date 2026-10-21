"""Bounded, parameterized queries over completed research snapshots."""

import json
import os
from pathlib import Path

import chess

from .storage import identifier


class StoreUnavailable(Exception):
    pass


class TrinoReader:
    def query(self, sql, parameters=()):
        from trino.auth import JWTAuthentication
        from trino.dbapi import connect

        connection = None
        try:
            token = Path(os.environ["OPENINGS_TRINO_TOKEN_FILE"]).read_text().strip()
            connection = connect(
                host=os.environ["OPENINGS_TRINO_HOST"],
                port=int(os.getenv("OPENINGS_TRINO_PORT", "8443")),
                user=os.getenv("OPENINGS_TRINO_USER", "openings-api"),
                http_scheme="https",
                auth=JWTAuthentication(token),
                verify=os.environ["OPENINGS_TRINO_CA_FILE"],
                request_timeout=30,
                max_attempts=2,
                source="openings-research-api",
                session_properties={"query_max_run_time": "30s"},
            )
            cursor = connection.cursor()
            cursor.execute(sql, list(parameters)) if parameters else cursor.execute(sql)
            rows = cursor.fetchmany(1001)
            if len(rows) > 1000:
                cursor.cancel()
                raise ValueError("Query exceeded bounded response size")
            names = [item[0] for item in cursor.description]
            return [dict(zip(names, row, strict=True)) for row in rows]
        except Exception:
            raise StoreUnavailable("Research store is unavailable") from None
        finally:
            if connection:
                connection.close()


class ResearchReader:
    def __init__(self, db, namespace="research.openings_research"):
        parts = namespace.split(".")
        if len(parts) != 2:
            raise ValueError("Expected catalog.schema")
        self.namespace = ".".join(identifier(p) for p in parts)
        self.db = db

    def table(self, name):
        return f"{self.namespace}.{identifier(name)}"

    def openings(self, limit=50, offset=0):
        return self.db.query(
            f"""
            SELECT opening_id, opening, run_id, completed_at FROM (
              SELECT opening_id, opening, run_id, completed_at,
                row_number() OVER (PARTITION BY opening_id ORDER BY completed_at DESC, run_id DESC) AS rn
              FROM {self.table("research_runs")} WHERE status = 'completed'
            ) ranked WHERE rn = 1 ORDER BY opening, opening_id OFFSET ? LIMIT ?
        """,
            (offset, limit),
        )

    def runs(self, opening_id, limit=50):
        return self.db.query(
            f"""SELECT run_id, opening_id, opening, status, created_at, completed_at
            FROM {self.table("research_runs")} WHERE opening_id = ?
            ORDER BY created_at DESC, run_id DESC LIMIT ?""",
            (opening_id, limit),
        )

    def completed(self, run_id):
        rows = self.db.query(
            f"""SELECT run_id, opening_id, opening, completed_at
            FROM {self.table("research_runs")} WHERE run_id = ? AND status = 'completed' LIMIT 1""",
            (run_id,),
        )
        if not rows:
            raise LookupError("Completed run not found")
        return rows[0]

    def records(self, run_id, kind, limit=100, offset=0):
        self.completed(run_id)
        if kind == "claims":
            projection = "record_id, candidate_id, claim_id, text, category, side, position_id, review_status"
            table = "claims"
        elif kind == "lines":
            rows = self.db.query(
                f"""SELECT r.record_id, r.candidate_id, r.line_id, r.name, r.review_status,
                l.moves_uci, p.normalized_fen AS start_fen
                FROM {self.table("opening_lines")} r
                JOIN {self.table("lines")} l ON l.line_id = r.line_id
                JOIN {self.table("positions")} p ON p.position_id = l.start_position_id
                WHERE r.run_id = ? ORDER BY r.record_id OFFSET ? LIMIT ?""",
                (run_id, offset, limit),
            )
            for row in rows:
                moves = row["moves_uci"]
                if isinstance(moves, str):
                    moves = json.loads(moves)
                board = chess.Board(row["start_fen"] + " 0 1")
                row["moves_san"] = []
                for uci in moves:
                    move = chess.Move.from_uci(uci)
                    if move not in board.legal_moves:
                        raise ValueError("Stored line contains an illegal move")
                    row["moves_san"].append(board.san(move))
                    board.push(move)
                row["moves_uci"] = moves
                row["end_fen"] = board.fen()
            return rows
        else:
            raise ValueError("Unknown record kind")
        return self.db.query(
            f"SELECT {projection} FROM {self.table(table)} WHERE run_id = ? "
            "ORDER BY record_id OFFSET ? LIMIT ?",
            (run_id, offset, limit),
        )

    def evidence(self, run_id, candidate_id, limit=100, offset=0):
        self.completed(run_id)
        return self.db.query(
            f"""SELECT e.source_version_id, e.excerpt, e.relation, s.url, v.title
            FROM {self.table("claim_evidence")} e
            JOIN {self.table("source_versions")} v ON v.source_version_id = e.source_version_id
            JOIN {self.table("sources")} s ON s.source_id = v.source_id
            WHERE e.run_id = ? AND e.candidate_id = ?
            ORDER BY e.evidence_id OFFSET ? LIMIT ?""",
            (run_id, candidate_id, offset, limit),
        )

    def coverage(self, run_id):
        self.completed(run_id)
        rows = self.db.query(
            f"SELECT report_json FROM {self.table('coverage_reports')} WHERE run_id = ? LIMIT 1", (run_id,)
        )
        return json.loads(rows[0]["report_json"]) if rows else None

    def compare(self, before, after):
        left, right = self.completed(before), self.completed(after)
        if left["opening_id"] != right["opening_id"]:
            raise ValueError("Comparison requires two runs for the same opening")
        result = {"before": before, "after": after}
        for name, table, key in [("claims", "claims", "claim_id"), ("lines", "opening_lines", "line_id")]:
            ids = []
            for run in (before, after):
                data = self.db.query(
                    f"SELECT DISTINCT {key} FROM {self.table(table)} WHERE run_id = ? LIMIT 1000", (run,)
                )
                if len(data) == 1000:
                    raise ValueError("Comparison exceeds 999 unique records per kind")
                ids.append({r[key] for r in data})
            result[name] = {
                "added": sorted(ids[1] - ids[0]),
                "removed": sorted(ids[0] - ids[1]),
                "retained": len(ids[0] & ids[1]),
            }
        return result
