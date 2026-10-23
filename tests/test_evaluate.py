import io
import json
import urllib.error

import chess
import pytest
from test_pipeline import MemoryStore, config, execute_all

from openings_research.evaluate import EngineClient, book_lines, evaluate_book, evaluation_rows
from openings_research.pipeline import Pipeline


class FakeEngine:
    """Answers like christufa/chess-engines /v1/analyse: the first `multipv` legal moves, best first."""

    engine = "stockfish"

    def __init__(self):
        self.calls = []

    def analyse(self, fen, depth, multipv):
        self.calls.append(fen)
        board = chess.Board(fen)
        lines = []
        for rank, move in enumerate(list(board.legal_moves)[:multipv], 1):
            san = board.san(move)
            lines.append({
                "rank": rank, "uci": move.uci(), "san": san,
                "score": {"cp": 40 - 25 * rank, "mate": None}, "white_score": {"cp": 0, "mate": None},
                "depth": depth, "seldepth": depth + 4, "nodes": 1000, "pv": [move.uci()], "pv_san": [san],
            })
        return {
            "fen": fen, "turn": "white", "engine": {"name": "stockfish", "version": "17.1", "id": "Stockfish 17.1"},
            "limit": {"depth": depth, "movetime_ms": None}, "multipv": multipv, "outcome": None,
            "lines": lines, "time_ms": 5,
        }


def published_store():
    store = MemoryStore()
    execute_all(Pipeline(store, "published", config()))
    store.upsert("research_runs", [{**r, "opening": "Italian Game"} for r in store.read("research_runs")])
    return store


def quiet(*_):
    pass


def test_every_book_position_is_evaluated_once():
    store, engine = published_store(), FakeEngine()
    lines = book_lines(store)
    assert [line["moves_uci"] for line in lines] == [["e2e4", "e7e5", "g1f3", "b8c6", "f1c4"]]
    assert evaluate_book(store, engine, depth=12, multipv=3, log=quiet) == 6  # start + 5 plies
    rows = store.read("move_evaluations")
    assert len(rows) == 18 and {r["rank"] for r in rows} == {1, 2, 3}
    assert all(r["engine"] == "stockfish" and r["engine_version"] == "17.1" for r in rows)
    # Idempotent: nothing left to do at this depth; a deeper pass evaluates again.
    assert evaluate_book(store, engine, depth=12, multipv=3, log=quiet) == 0
    assert evaluate_book(store, engine, depth=16, multipv=3, log=quiet) == 6


def test_small_batches_and_parallel_requests_cover_every_position():
    store, engine = published_store(), FakeEngine()
    assert evaluate_book(store, engine, depth=12, multipv=2, batch=4, parallel=3, log=quiet) == 6
    assert len({r["position_id"] for r in store.read("move_evaluations")}) == 6
    assert len(engine.calls) == 6


def test_rows_keep_scores_and_are_keyed_per_position_engine_depth_move():
    fen = chess.STARTING_FEN
    analysis = {"engine": {"name": "stockfish", "version": "17.1"}, "lines": [
        {"rank": 1, "uci": "e2e4", "san": "e4", "score": {"cp": 30, "mate": None}, "depth": 20, "pv": ["e2e4", "e7e5"]},
        {"rank": 2, "uci": "f2f3", "san": "f3", "score": {"cp": None, "mate": -12}, "depth": 20, "pv": []},
    ]}
    a, b = evaluation_rows("pos", fen, analysis, 20)
    assert (a["move_uci"], a["move_san"], a["score_cp"], a["mate"], a["pv"]) == ("e2e4", "e4", 30, None, ["e2e4", "e7e5"])
    assert (b["score_cp"], b["mate"]) == (None, -12)
    assert a["evaluation_id"] != b["evaluation_id"]
    assert evaluation_rows("pos", fen, analysis, 20)[0]["evaluation_id"] == a["evaluation_id"]


def test_no_legal_moves_gives_no_rows():
    analysis = {"engine": {"name": "stockfish", "version": "19"}, "outcome": "checkmate", "lines": []}
    assert evaluation_rows("pos", "fen", analysis, 20) == []


def test_client_retries_busy_answers_then_fails_on_others(monkeypatch):
    answers = [503, 504, 200]
    seen, slept = [], []

    def fake_urlopen(request, timeout):
        seen.append(json.loads(request.data))
        code = answers.pop(0)
        if code != 200:
            raise urllib.error.HTTPError(request.full_url, code, "busy", {"Retry-After": "5"}, io.BytesIO())
        return io.BytesIO(b'{"lines": []}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = EngineClient("http://engines/", "stockfish", sleep=slept.append)
    assert client.analyse("fen", 20, 5) == {"lines": []}
    assert seen[0] == {"fen": "fen", "engine": "stockfish", "depth": 20, "multipv": 5}  # no extra fields: 422
    assert slept == [5.0, 10.0]
    answers[:] = [422]
    with pytest.raises(urllib.error.HTTPError):
        client.analyse("fen", 20, 5)
