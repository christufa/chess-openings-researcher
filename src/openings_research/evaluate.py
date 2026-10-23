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
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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
    """POST /v1/analyse on christufa/chess-engines (docs/api.md there).

    In the cluster no auth is needed: network policy is the boundary. The service answers
    503 (queue full) or 504 (engine restarted) with Retry-After when busy; those are retried
    with backoff, anything else fails the job.
    """

    RETRYABLE = {503, 504}

    def __init__(self, url: str, engine: str, timeout: float = 60, attempts: int = 6, sleep=time.sleep):
        self.url, self.engine, self.timeout, self.attempts, self.sleep = url.rstrip("/"), engine, timeout, attempts, sleep

    def analyse(self, fen: str, depth: int, multipv: int) -> dict:
        body = json.dumps({"fen": fen, "engine": self.engine, "depth": depth, "multipv": multipv}).encode()
        for attempt in range(self.attempts):
            request = urllib.request.Request(
                f"{self.url}/v1/analyse", data=body, headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code not in self.RETRYABLE or attempt == self.attempts - 1:
                    raise
                wait = float(error.headers.get("Retry-After") or 5)
                self.sleep(wait * (attempt + 1))
        raise RuntimeError("unreachable")


def evaluation_rows(position_id: str, fen: str, analysis: dict, depth: int) -> list[dict]:
    """The engine service's response as move_evaluations rows.

    The only place that knows the response shape (christufa/chess-engines, /v1): {"engine":
    {"name", "version"}, "lines": [{"rank", "uci", "san", "score": {"cp", "mate"}, "depth",
    "pv": [uci, ...]}]}. `score` is from the side to move's view, as the tree expects; exactly
    one of cp and mate is set. With no legal moves `lines` is empty, so no rows.
    """
    engine = analysis["engine"]
    now = datetime.now(UTC).isoformat()
    rows = []
    for line in analysis["lines"]:
        score = line["score"]
        rows.append(
            {
                "evaluation_id": stable_id(position_id, engine["name"], engine["version"], depth, line["uci"]),
                "position_id": position_id,
                "fen": fen,
                "engine": engine["name"],
                "engine_version": engine["version"],
                "depth": int(line.get("depth") or depth),
                "rank": int(line["rank"]),
                "move_uci": line["uci"],
                "move_san": line["san"],
                "score_cp": score.get("cp"),
                "mate": score.get("mate"),
                "pv": list(line.get("pv") or []),
                "evaluated_at": now,
            }
        )
    return rows


def evaluate_book(store, client, depth: int, multipv: int, batch: int = 25, parallel: int = 4, log=print) -> int:
    """Evaluates book positions not yet evaluated at this depth; returns how many it did.

    Sends `parallel` requests at a time (the service runs 2 engines per pod, 1-3 pods) and
    writes every `batch` positions, so an interrupted run keeps what it finished.
    """
    tree = BookTree(book_lines(store))
    done = {
        (r["position_id"], r["engine"])
        for r in store.read("move_evaluations")
        if r["depth"] >= depth
    }
    pending = [p for p in sorted(tree.positions.values(), key=lambda p: p.fen) if (p.position_id, client.engine) not in done]
    log(json.dumps({"event": "evaluation_plan", "positions": len(tree.positions), "pending": len(pending)}))
    count = 0
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        for start in range(0, len(pending), batch):
            chunk = pending[start : start + batch]
            fens = [p.fen + " 0 1" for p in chunk]
            analyses = pool.map(lambda fen: client.analyse(fen, depth, multipv), fens)
            rows = [row for p, fen, a in zip(chunk, fens, analyses) for row in evaluation_rows(p.position_id, fen, a, depth)]
            store.upsert("move_evaluations", rows)
            count += len(chunk)
            log(json.dumps({"event": "evaluation_progress", "done": count, "pending": len(pending)}))
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
