import pytest
from fastapi.testclient import TestClient
from test_pipeline import MemoryStore, config, execute_all
from test_serving import memory_reader

from openings_research.api import create_app
from openings_research.pipeline import Pipeline
from openings_research.serving import ResearchReader
from openings_research.tree import START, BookTree

START_FEN = START["normalized_fen"]


def line(opening, name, *moves):
    return {"opening": opening, "name": name, "start_fen": START_FEN, "moves_uci": list(moves)}


def test_book_moves_merge_lines_and_openings():
    tree = BookTree([
        line("Italian Game", "Giuoco Piano", "e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5"),
        line("Italian Game", "Two Knights", "e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6"),
        line("Ruy Lopez", "Ruy Lopez", "e2e4", "e7e5", "g1f3", "b8c6", "f1b5"),
    ])
    root = tree.lookup(START_FEN)
    assert root["side_to_move"] == "white" and root["in_book"]
    assert [m["san"] for m in root["moves"]] == ["e4"]
    assert root["moves"][0]["openings"] == ["Italian Game", "Ruy Lopez"]
    after_nc6 = tree.lookup("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3")
    assert [m["san"] for m in after_nc6["moves"]] == ["Bc4", "Bb5"]  # two Italian lines pass Bc4
    bc4 = after_nc6["moves"][0]
    assert bc4["lines"] == ["Giuoco Piano", "Two Knights"] and bc4["continues"]
    leaf = tree.lookup(after_nc6["moves"][1]["fen"])
    assert leaf["names"] == ["Ruy Lopez"] and leaf["moves"] == []


def test_transpositions_meet_at_one_node():
    tree = BookTree([
        line("Queen's Gambit Declined", "QGD", "d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6"),
        line("Queen's Gambit Declined", "QGD via Nf6", "d2d4", "g8f6", "c2c4", "e7e6", "b1c3", "d7d5"),
    ])
    a = tree.lookup("rnbqkb1r/ppp2ppp/4pn2/3p4/2PP4/2N5/PP2PPPP/R1BQKBNR w KQkq - 2 4")
    assert a["in_book"] and sorted(a["names"]) == ["QGD", "QGD via Nf6"]


def test_positions_outside_the_book_and_bad_input():
    tree = BookTree([line("Italian Game", "Italian", "e2e4", "e7e5")])
    off = tree.lookup("rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1")
    assert not off["in_book"] and off["moves"] == []
    for bad in ["not a fen", "8/8/8/8/8/8/8/8 w - - 0 1", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1 extra"]:
        with pytest.raises(ValueError):
            tree.lookup(bad)


def test_reference_variations_name_positions_and_rank_after_research():
    from openings_research.tree import rank_moves

    reference = [
        {"eco": "C50", "name": "Italian Game", "moves_uci": ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4"]},
        {"eco": "C60", "name": "Ruy Lopez", "moves_uci": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"]},
        {"eco": "C44", "name": "Scotch Game", "moves_uci": ["e2e4", "e7e5", "g1f3", "b8c6", "d2d4"]},
    ]
    tree = BookTree([line("Italian Game", "Giuoco Piano", "e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5")], reference)
    after_nc6 = tree.lookup("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3")
    assert [(m["san"], m["book"], m["reference"]) for m in after_nc6["moves"]] == [
        ("Bc4", True, True), ("Bb5", False, True), ("d4", False, True)]
    assert [m["variations"] for m in after_nc6["moves"]] == [1, 1, 1]
    assert tree.lookup(START_FEN)["moves"][0]["variations"] == 3  # all three named lines start 1.e4
    ruy = tree.lookup(after_nc6["moves"][1]["fen"])
    assert ruy["reference"] == [{"eco": "C60", "name": "Ruy Lopez"}] and not ruy["in_book"] and ruy["in_reference"]
    ranked = rank_moves(after_nc6, [ev("d2d4", "d4", 40), ev("f1b5", "Bb5", 30, rank=2), ev("h2h3", "h3", 10, rank=3)])
    assert [(m["san"], m["quality"]) for m in ranked["moves"]] == [
        ("Bc4", "book"), ("d4", "reference"), ("Bb5", "reference"), ("h3", "good")]
    assert tree.lookup("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")["in_book"]


def test_the_packaged_reference_book_parses():
    from openings_research.reference import reference_lines, search

    lines = reference_lines()
    assert len(lines) > 3000 and all(line["moves_uci"] for line in lines)
    assert search("ruy lopez berlin")[0]["eco"] == "C65"
    english = [(v["eco"], v["name"]) for v in search("najdorf english attack", 50)]
    assert len(english) == len(set(english))  # once per name, though listed under several move orders
    assert search("   ") == []


def test_smoke_fixtures_stay_out_of_the_book():
    store = MemoryStore()
    execute_all(Pipeline(store, "smoke", config()))  # the fixture opening is "__smoke_italian__"
    assert ResearchReader(memory_reader(store)).book_lines() == []


def test_tree_endpoint_serves_published_lines():
    store = MemoryStore()
    execute_all(Pipeline(store, "published", config()))
    # Only the authored fixture can be published offline; present it as a real opening.
    store.upsert("research_runs", [{**r, "opening": "Italian Game"} for r in store.read("research_runs")])
    with TestClient(create_app(ResearchReader(memory_reader(store)))) as client:
        root = client.get("/api/v1/tree").json()
        assert [m["san"] for m in root["moves"] if m["book"]] == ["e4"] and root["moves"][0]["san"] == "e4"
        assert len(root["moves"]) == 20 and all(m["reference"] for m in root["moves"])  # every first move is named
        fen = root["moves"][0]["fen"]
        after_e4 = client.get("/api/v1/tree", params={"fen": fen}).json()
        assert after_e4["moves"][0]["san"] == "e5" and after_e4["reference"] == [{"eco": "B00", "name": "King's Pawn Game"}]
        assert client.get("/api/v1/tree", params={"fen": "not a fen at all"}).status_code == 400
        found = client.get("/api/v1/names", params={"q": "najdorf english attack"}).json()
        assert found["items"][0]["name"] == "Sicilian Defense: Najdorf Variation, English Attack"
        assert found["items"][0]["moves_uci"][-1] == "c1e3" and found["source"].startswith("lichess-org/chess-openings@")
        assert client.get("/api/v1/names", params={"q": "B90"}).json()["items"][0]["eco"] == "B90"
        assert client.get("/api/v1/names", params={"q": "x"}).status_code == 422


def ev(uci, san, cp=None, mate=None, rank=1, depth=20):
    return {"move_uci": uci, "move_san": san, "score_cp": cp, "mate": mate, "depth": depth, "rank": rank,
            "engine": "stockfish", "engine_version": "17.1"}


def test_book_moves_come_first_even_when_the_engine_dislikes_them():
    from openings_research.tree import rank_moves

    tree = BookTree([line("King's Gambit", "King's Gambit", "e2e4", "e7e5", "f2f4"),
                     line("Vienna", "Vienna", "e2e4", "e7e5", "b1c3")])
    position = tree.lookup("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    ranked = rank_moves(position, [
        ev("g1f3", "Nf3", cp=35, rank=1), ev("b1c3", "Nc3", cp=20, rank=2), ev("f2f4", "f4", cp=-60, rank=3),
        ev("d2d4", "d4", cp=5, rank=4), ev("d1h5", "Qh5", cp=-120, rank=5), ev("g2g4", "g4", mate=-9, rank=6),
        ev("a1a3", "Ra3", cp=0, rank=7),  # illegal here: must be ignored
    ])
    moves = [(m["san"], m["quality"]) for m in ranked["moves"]]
    # Book first (Nc3 15 behind, f4 95 behind), then engine moves by quality, then loss.
    assert moves == [("Nc3", "book"), ("f4", "book"), ("Nf3", "good"), ("d4", "good"), ("Qh5", "poor"), ("g4", "poor")]
    f4 = ranked["moves"][1]
    assert f4["engine_quality"] == "weaker" and f4["loss_cp"] == 95 and f4["book"]
    assert ranked["evaluated"] and ranked["engine"] == {"name": "stockfish", "version": "17.1", "depth": 20}


def test_without_evaluations_the_book_is_served_unchanged():
    from openings_research.tree import rank_moves

    tree = BookTree([line("Italian Game", "Italian", "e2e4")])
    ranked = rank_moves(tree.lookup(START_FEN), [])
    assert [(m["san"], m["quality"], m["loss_cp"]) for m in ranked["moves"]] == [("e4", "book", None)]
    assert not ranked["evaluated"] and ranked["engine"] is None


def test_mate_scores_outrank_centipawns():
    from openings_research.tree import score_value

    assert score_value(None, 3) > score_value(None, 7) > score_value(900, None) > score_value(None, -7) > score_value(None, -3)
