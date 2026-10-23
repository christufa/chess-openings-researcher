"""The opening book as a move tree, built from the latest published line of every opening.

Positions are keyed by the same identity the pipeline uses (`position_record`): placement,
side to move, castling and legal en passant, without move counters. Different move orders
that reach the same position therefore meet at one node, which is how transpositions show up.
"""

from dataclasses import dataclass, field

import chess

from .contracts import position_record

START = position_record(chess.Board())


@dataclass
class BookMove:
    uci: str
    san: str
    to_position_id: str
    to_fen: str
    openings: set[str] = field(default_factory=set)
    lines: set[str] = field(default_factory=set)  # names of researched lines that play this move


@dataclass
class BookPosition:
    position_id: str
    fen: str
    moves: dict[str, BookMove] = field(default_factory=dict)
    named: set[str] = field(default_factory=set)  # names of lines that end exactly here
    openings: set[str] = field(default_factory=set)  # openings whose lines pass through here


def board_for(fen: str) -> chess.Board:
    """A board from a full FEN, or from the first four fields (counters are not identity)."""
    fields = fen.split()
    if not 4 <= len(fields) <= 6 or len(fen) > 100:
        raise ValueError("Expected a FEN")
    board = chess.Board(" ".join(fields[:4]) + " 0 1")
    position_record(board)  # rejects invalid and non-standard positions
    return board


class BookTree:
    def __init__(self, lines: list[dict]):
        """`lines`: opening, line name, start FEN (normalized) and UCI moves of each published line."""
        self.positions: dict[str, BookPosition] = {}
        for line in lines:
            board = board_for(line["start_fen"])
            node = self._position(board)
            node.openings.add(line["opening"])
            for uci in line["moves_uci"]:
                move = chess.Move.from_uci(uci)
                if move not in board.legal_moves:
                    raise ValueError("Stored line contains an illegal move")
                san = board.san(move)
                board.push(move)
                child = self._position(board)
                child.openings.add(line["opening"])
                edge = node.moves.setdefault(
                    uci, BookMove(uci, san, child.position_id, child.fen)
                )
                edge.openings.add(line["opening"])
                edge.lines.add(line["name"])
                node = child
            node.named.add(line["name"])

    def _position(self, board: chess.Board) -> BookPosition:
        record = position_record(board)
        return self.positions.setdefault(
            record["position_id"], BookPosition(record["position_id"], record["normalized_fen"])
        )

    def lookup(self, fen: str) -> dict:
        board = board_for(fen)
        record = position_record(board)
        node = self.positions.get(record["position_id"])
        moves = sorted(
            node.moves.values() if node else [],
            key=lambda m: (-len(m.lines), -len(m.openings), m.san),  # most-researched first
        )
        return {
            "position_id": record["position_id"],
            "fen": record["normalized_fen"],
            "side_to_move": "white" if board.turn == chess.WHITE else "black",
            "in_book": node is not None,
            "names": sorted(node.named) if node else [],
            "openings": sorted(node.openings) if node else [],
            "moves": [
                {
                    "uci": m.uci,
                    "san": m.san,
                    "book": True,
                    "fen": m.to_fen,
                    "openings": sorted(m.openings),
                    "lines": sorted(m.lines),
                    "continues": bool(self.positions[m.to_position_id].moves),
                }
                for m in moves
            ],
        }
