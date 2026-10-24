"""The reference book: ECO-named variations from lichess-org/chess-openings (CC0), packaged.

Static data versioned with the code (eco/README.md), so the explorer needs no fetch and
no table for it. Each entry is a name and the moves that define it; the book tree merges them
beside the researched lines, so every position gets its standard name.
"""

import csv
from functools import cache
from importlib import resources

import chess

COMMIT = "a6189a30dc273ccb21fc2536a9a2fefd5592a67a"
SOURCE = f"lichess-org/chess-openings@{COMMIT[:7]}"


def parse_pgn_moves(pgn: str) -> list[str]:
    """UCI moves from a movetext like "1. e4 e5 2. Nf3"; raises on an illegal or unknown move."""
    board = chess.Board()
    moves = []
    for token in pgn.split():
        if token.rstrip(".").isdigit():
            continue
        move = board.parse_san(token)
        board.push(move)
        moves.append(move.uci())
    return moves


@cache
def reference_lines() -> tuple[dict, ...]:
    """Every named variation: {"eco", "name", "moves_uci"}, in file order (by ECO)."""
    lines = []
    folder = resources.files("openings_research") / "eco"
    for letter in "abcde":
        with (folder / f"{letter}.tsv").open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                lines.append({"eco": row["eco"], "name": row["name"], "moves_uci": parse_pgn_moves(row["pgn"])})
    return tuple(lines)


def search(query: str, limit: int = 20) -> list[dict]:
    """Named variations whose name (or ECO code) contains every word of `query`, shortest first,
    once per name."""
    words = query.casefold().split()
    if not words:
        return []
    matches = [
        line for line in reference_lines()
        if all(word in f"{line['eco']} {line['name']}".casefold() for word in words)
    ]
    matches.sort(key=lambda line: (len(line["moves_uci"]), line["name"]))
    shortest = {}  # a name can be listed under several move orders: keep its shortest
    for line in matches:
        shortest.setdefault((line["eco"], line["name"]), line)
    return [{**line, "moves_uci": list(line["moves_uci"])} for line in list(shortest.values())[:limit]]
