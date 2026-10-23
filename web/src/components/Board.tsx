import { Chess } from "chess.js";
import { Chessboard } from "react-chessboard";
import { fullFen } from "../api";

interface Props {
  fen: string;
  lastMove?: string; // UCI of the move that reached this position
  orientation: "white" | "black";
  onMove: (uci: string) => void;
}

/** The current position. Dragging a legal move plays it (into the tree, or off the book). */
export function Board({ fen, lastMove, orientation, onMove }: Props) {
  const highlight = lastMove
    ? Object.fromEntries([lastMove.slice(0, 2), lastMove.slice(2, 4)].map((sq) => [sq, { background: "rgba(155, 199, 0, 0.35)" }]))
    : {};
  // The board fills its container's height, so the container must be square.
  return (
    <div className="aspect-square w-full">
    <Chessboard
      options={{
        position: fullFen(fen),
        boardOrientation: orientation,
        squareStyles: highlight,
        darkSquareStyle: { backgroundColor: "#b58863" },
        lightSquareStyle: { backgroundColor: "#f0d9b5" },
        animationDurationInMs: 180,
        onPieceDrop: ({ sourceSquare, targetSquare }) => {
          if (!targetSquare) return false;
          const game = new Chess(fullFen(fen));
          try {
            const move = game.move({ from: sourceSquare, to: targetSquare, promotion: "q" });
            onMove(move.from + move.to + (move.promotion ?? ""));
            return true;
          } catch {
            return false; // illegal: the piece snaps back
          }
        },
      }}
    />
    </div>
  );
}
