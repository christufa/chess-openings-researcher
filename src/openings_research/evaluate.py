"""Evaluate every book position with the shared engine service (christufa/chess-engines).

For each position in the published book, ask the engine for its top `multipv` moves and store
them in `move_evaluations`: one row per (position, engine, engine version, depth, move). The
tree then ranks book moves by these scores and offers the engine's non-book moves beside them.
Positions already evaluated with the same engine, version and depth are skipped, so a rerun
only evaluates what the latest research added.
"""

import argparse
import json
import os
import urllib.request
from datetime import UTC, datetime

from .contracts import stable_id
from .tree import BookTree


def book_lines(store) -> list[dict]:
    """Each opening's latest completed lines, from the store (Spark tables or test memory)."""
    latest = {}
    for run in store.read("research_runs", status="completed"):
        if run["opening"].startswith("__"):
            continue
        best = latest.get(run["opening_id"])
        if best is None or (run["completed_at"], run["run_id"]) > (best["completed_at"], best["run_id"]):
            latest[run["opening_id"]] = run
    runs = {r["run_id"]: r["opening"] for r in latest.values()}
    lines = {r["line_id"]: r for r in store.read("lines")}
    fens = {p["position_id"]: p["normalized_fen"] for p in store.read("positions")}
    return [
        {
            "opening": runs[record["run_id"]],
            "name": record["name"],
            "moves_uci": list(lines[record["line_id"]]["moves_uci"]),
            "start_fen": fens[lines[record["line_id"]]["start_position_id"]],
        }
        for record in store.read("opening_lines")
        if record["run_id"] in runs
    ]


class EngineClient:
    """POST /v1/analyse on the engine service; in-cluster calls need no auth."""

    def __init__(self, url: str, engine: str, timeout: float = 120):
        self.url, self.engine, self.timeout = url.rstrip("/"), engine, timeout

    def analyse(self, fen: str, depth: int, multipv: int) -> dict:
        body = json.dumps({"fen": fen, "engine": self.engine, "depth": depth, "multipv": multipv}).encode()
        request = urllib.request.Request(
            f"{self.url}/v1/analyse", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.load(response)


def evaluation_rows(position_id: str, fen: str, analysis: dict, depth: int) -> list[dict]:
    """The engine service's response as move_evaluations rows.

    The only place that knows the response shape: {"engine": {"name", "version"}, "lines": [
    {"rank", "move": {"uci", "san"}, "score": {"cp", "mate"}, "depth", "pv": [uci, ...]}]}, with
    scores from the side to move's point of view.
    """
    engine = analysis["engine"]
    now = datetime.now(UTC).isoformat()
    rows = []
    for line in analysis["lines"]:
        move, score = line["move"], line["score"]
        rows.append(
            {
                "evaluation_id": stable_id(position_id, engine["name"], engine["version"], depth, move["uci"]),
                "position_id": position_id,
                "fen": fen,
                "engine": engine["name"],
                "engine_version": engine["version"],
                "depth": int(line.get("depth") or depth),
                "rank": int(line["rank"]),
                "move_uci": move["uci"],
                "move_san": move["san"],
                "score_cp": score.get("cp"),
                "mate": score.get("mate"),
                "pv": list(line.get("pv") or []),
                "evaluated_at": now,
            }
        )
    return rows


def evaluate_book(store, client, depth: int, multipv: int, batch: int = 25, log=print) -> int:
    """Evaluates book positions not yet evaluated at this depth; returns how many it did."""
    tree = BookTree(book_lines(store))
    done = {
        (r["position_id"], r["engine"])
        for r in store.read("move_evaluations")
        if r["depth"] >= depth
    }
    pending = [p for p in sorted(tree.positions.values(), key=lambda p: p.fen) if (p.position_id, client.engine) not in done]
    log(json.dumps({"event": "evaluation_plan", "positions": len(tree.positions), "pending": len(pending)}))
    rows, count = [], 0
    for position in pending:
        fen = position.fen + " 0 1"
        rows += evaluation_rows(position.position_id, fen, client.analyse(fen, depth, multipv), depth)
        count += 1
        if count % batch == 0:
            store.upsert("move_evaluations", rows)
            rows = []
            log(json.dumps({"event": "evaluation_progress", "done": count, "pending": len(pending)}))
    store.upsert("move_evaluations", rows)
    log(json.dumps({"event": "evaluation_completed", "evaluated": count}))
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", default="stockfish")
    parser.add_argument("--depth", type=int, default=20)
    parser.add_argument("--multipv", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.depth <= 40 or not 1 <= args.multipv <= 10:
        parser.error("depth must be 1-40 and multipv 1-10")
    from pyspark.sql import SparkSession

    from .iceberg import IcebergStore, spark_config

    builder = SparkSession.builder.appName("openings-evaluate")
    for key, value in spark_config().items():
        builder = builder.config(key, value)
    spark = builder.getOrCreate()
    try:
        store = IcebergStore(spark, os.getenv("OPENINGS_CATALOG", "research"), "openings_research")
        store.bootstrap()  # creates move_evaluations on first use
        client = EngineClient(os.environ["OPENINGS_ENGINE_URL"], args.engine)
        evaluate_book(store, client, args.depth, args.multipv)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
