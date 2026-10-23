"""Bounded, parameterized queries over completed research snapshots."""

import json
import os
import re
import threading
from pathlib import Path

import chess

from .storage import identifier


class StoreUnavailable(Exception):
    pass


class ArrowSQL:
    """Runs the reader's SQL in a throwaway in-memory DuckDB over Arrow tables.

    `load(name)` returns one table as Arrow. Each `<namespace>.<table>` in the SQL is
    swapped for that table registered under a local name, so only tables a query names
    are loaded, and nothing can be written back.
    """

    def __init__(self, load, namespace="research.openings_research"):
        self.load = load
        self.pattern = re.compile(re.escape(namespace) + r"\.(\w+)\b")

    def query(self, sql, parameters=()):
        import duckdb

        connection = duckdb.connect(":memory:")
        try:
            for name in sorted(set(self.pattern.findall(sql))):
                connection.register(f"iceberg_{name}", self.load(name))
            cursor = connection.execute(self.pattern.sub(r"iceberg_\1", sql), list(parameters))
            rows = cursor.fetchmany(1001)
            if len(rows) > 1000:
                raise ValueError("Query exceeded bounded response size")
            names = [item[0] for item in cursor.description]
            return [dict(zip(names, row, strict=True)) for row in rows]
        finally:
            connection.close()


class IcebergReader:
    """Reads completed research straight from the Iceberg REST catalog (no query engine).

    Signs in with the pod's projected catalog token, re-read whenever it rotates, and asks
    for vended credentials, so the API holds no storage role of its own. Tables are small:
    each is scanned whole and cached until its snapshot changes.
    """

    def __init__(self, namespace="research.openings_research", catalog=None):
        self.namespace = namespace
        self.schema = namespace.split(".")[1]
        self._fixed = catalog  # tests pass a local catalog; production builds a REST one
        self._rest, self._token = None, None
        self._snapshots = {}
        self._lock = threading.Lock()
        self.sql = ArrowSQL(self._table, namespace)

    def catalog(self):
        if self._fixed is not None:
            return self._fixed
        from pyiceberg.catalog.rest import RestCatalog

        token = Path(os.environ["OPENINGS_CATALOG_TOKEN_FILE"]).read_text().strip()
        if self._rest is None or token != self._token:
            self._rest = RestCatalog(
                "research",
                uri=os.environ["OPENINGS_CATALOG_URI"],
                warehouse=os.environ["OPENINGS_WAREHOUSE"],
                token=token,
                # Lakekeeper vends a per-account SAS token; the fsspec ADLS backend uses it.
                **{"py-io-impl": "pyiceberg.io.fsspec.FsspecFileIO"},
            )
            self._token = token
        return self._rest

    def _table(self, name):
        table = self.catalog().load_table((self.schema, name))
        snapshot = table.current_snapshot()
        snapshot_id = snapshot.snapshot_id if snapshot else None
        cached = self._snapshots.get(name)
        if cached and cached[0] == snapshot_id:
            return cached[1]
        data = table.scan().to_arrow()
        self._snapshots[name] = (snapshot_id, data)
        return data

    def ping(self):
        with self._lock:
            try:
                self.catalog().list_tables(self.schema)
            except Exception:
                raise StoreUnavailable("Research store is unavailable") from None

    def query(self, sql, parameters=()):
        with self._lock:
            try:
                return self.sql.query(sql, parameters)
            except Exception:
                raise StoreUnavailable("Research store is unavailable") from None


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

    def book_lines(self, page=1000):
        """Every line of each opening's latest completed run, for the book tree (paged)."""
        rows, offset = [], 0
        while True:
            batch = self.db.query(
                f"""
                WITH latest AS (
                  SELECT run_id, opening FROM (
                    SELECT run_id, opening,
                      row_number() OVER (PARTITION BY opening_id ORDER BY completed_at DESC, run_id DESC) AS rn
                    FROM {self.table("research_runs")} WHERE status = 'completed'
                  ) ranked WHERE rn = 1
                )
                SELECT latest.opening, r.name, l.moves_uci, p.normalized_fen AS start_fen
                FROM latest
                JOIN {self.table("opening_lines")} r ON r.run_id = latest.run_id
                JOIN {self.table("lines")} l ON l.line_id = r.line_id
                JOIN {self.table("positions")} p ON p.position_id = l.start_position_id
                ORDER BY latest.opening, r.record_id OFFSET ? LIMIT ?""",
                (offset, page),
            )
            for row in batch:
                if isinstance(row["moves_uci"], str):
                    row["moves_uci"] = json.loads(row["moves_uci"])
            # Authored smoke fixtures (named "__...") never belong in the public book.
            rows.extend(row for row in batch if not row["opening"].startswith("__"))
            if len(batch) < page:
                return rows
            offset += page

    def evaluations(self, position_id, engine="stockfish"):
        """Engine evaluations for one position; none until the evaluation job has run."""
        try:
            return self.db.query(
                f"""SELECT move_uci, move_san, score_cp, mate, depth, rank, engine, engine_version
                FROM {self.table("move_evaluations")} WHERE position_id = ? AND engine = ?
                ORDER BY depth DESC, rank LIMIT 100""",
                (position_id, engine),
            )
        except StoreUnavailable:
            return []  # e.g. the table doesn't exist yet: serve the book without evaluations

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
