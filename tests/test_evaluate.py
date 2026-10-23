import chess
from test_pipeline import MemoryStore, config, execute_all

from openings_research.evaluate import book_lines, evaluate_book, evaluation_rows
from openings_research.pipeline import Pipeline


class FakeEngine:
    """Answers like the engine service: the first `multipv` legal moves, best first."""

    engine = "stockfish"

    def __init__(self):
        self.calls = []

    def analyse(self, fen, depth, multipv):
        self.calls.append(fen)
        board = chess.Board(fen)
        lines = []
        for rank, move in enumerate(list(board.legal_moves)[:multipv], 1):
            lines.append({"rank": rank, "move": {"uci": move.uci(), "san": board.san(move)},
                          "score": {"cp": 40 - 25 * rank, "mate": None}, "depth": depth, "pv": [move.uci()]})
        return {"engine": {"name": "stockfish", "version": "17.1"}, "lines": lines}


def published_store():
    store = MemoryStore()
    execute_all(Pipeline(store, "published", config()))
    store.upsert("research_runs", [{**r, "opening": "Italian Game"} for r in store.read("research_runs")])
    return store


def test_every_book_position_is_evaluated_once():
    store, engine = published_store(), FakeEngine()
    lines = book_lines(store)
    assert [line["moves_uci"] for line in lines] == [["e2e4", "e7e5", "g1f3", "b8c6", "f1c4"]]
    assert evaluate_book(store, engine, depth=12, multipv=3, log=lambda *_: None) == 6  # start + 5 plies
    rows = store.read("move_evaluations")
    assert len(rows) == 18 and {r["rank"] for r in rows} == {1, 2, 3}
    assert all(r["engine"] == "stockfish" and r["engine_version"] == "17.1" for r in rows)
    # Idempotent: nothing left to do at this depth; a deeper pass evaluates again.
    assert evaluate_book(store, engine, depth=12, multipv=3, log=lambda *_: None) == 0
    assert evaluate_book(store, engine, depth=16, multipv=3, log=lambda *_: None) == 6


def test_rows_keep_scores_and_are_keyed_per_position_engine_depth_move():
    fen = chess.STARTING_FEN
    analysis = {"engine": {"name": "stockfish", "version": "17.1"}, "lines": [
        {"rank": 1, "move": {"uci": "e2e4", "san": "e4"}, "score": {"cp": 30}, "depth": 20, "pv": ["e2e4", "e7e5"]},
        {"rank": 2, "move": {"uci": "f2f3", "san": "f3"}, "score": {"mate": -12}, "depth": 20, "pv": []},
    ]}
    a, b = evaluation_rows("pos", fen, analysis, 20)
    assert (a["score_cp"], a["mate"], a["pv"]) == (30, None, ["e2e4", "e7e5"])
    assert (b["score_cp"], b["mate"]) == (None, -12)
    assert a["evaluation_id"] != b["evaluation_id"]
    assert evaluation_rows("pos", fen, analysis, 20)[0]["evaluation_id"] == a["evaluation_id"]
