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
        assert [m["san"] for m in root["moves"]] == ["e4"] and root["moves"][0]["book"]
        fen = root["moves"][0]["fen"]
        assert client.get("/api/v1/tree", params={"fen": fen}).json()["moves"][0]["san"] == "e5"
        assert client.get("/api/v1/tree", params={"fen": "not a fen at all"}).status_code == 400
