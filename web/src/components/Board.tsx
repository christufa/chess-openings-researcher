import { Chess } from "chess.js";
import { Chessboard, defaultArrowOptions } from "react-chessboard";
import { fullFen } from "../api";
import { evalShare } from "../model";

export interface BoardArrow {
  uci: string;
  kind: "book" | "reference" | "engine";
}

interface Props {
  fen: string;
  lastMove?: string; // UCI of the move that reached this position
  orientation: "white" | "black";
  arrows: BoardArrow[]; // the moves the tree offers from here
  evaluation: { cp: number | null; mate: number | null } | null; // White's side
  onMove: (uci: string) => void;
}

const ARROW = { book: "rgba(52, 211, 153, 0.75)", reference: "rgba(167, 139, 250, 0.7)", engine: "rgba(109, 140, 255, 0.7)" };

export function evalText(evaluation: Props["evaluation"]): string {
  if (!evaluation) return "";
  if (evaluation.mate !== null) return `M${Math.abs(evaluation.mate)}`;
  const pawns = (evaluation.cp ?? 0) / 100;
  return `${pawns > 0 ? "+" : ""}${pawns.toFixed(1)}`;
}

/** The current position, with an evaluation bar. Dragging a legal move plays it (into the
 *  tree, or off the book); arrows show the moves the tree offers. */
export function Board({ fen, lastMove, orientation, arrows, evaluation, onMove }: Props) {
  const highlight = lastMove
    ? Object.fromEntries([lastMove.slice(0, 2), lastMove.slice(2, 4)].map((sq) => [sq, { background: "rgba(109, 140, 255, 0.32)" }]))
    : {};
  const share = evalShare(evaluation);
  const whiteBottom = orientation === "white";
  const label = evalText(evaluation);
  return (
    <div className="flex gap-2">
      <div
        className="relative w-3 shrink-0 overflow-hidden rounded-full bg-[#2b303b] ring-1 ring-line"
        role="meter"
        aria-label="Evaluation"
        aria-valuenow={Math.round(share * 100)}
        title={label ? `Evaluation ${label} (White's side)` : "No evaluation"}
      >
        <div
          className="absolute inset-x-0 bg-[#eef1f6] transition-all duration-500 ease-out"
          style={whiteBottom ? { bottom: 0, height: `${share * 100}%` } : { top: 0, height: `${share * 100}%` }}
        />
      </div>
      {/* The board fills its container's height, so the container must be square. */}
      <div className="relative aspect-square min-w-0 flex-1 overflow-hidden rounded-xl shadow-[0_12px_40px_rgb(0_0_0/0.45)] ring-1 ring-white/5">
        <Chessboard
          options={{
            position: fullFen(fen),
            boardOrientation: orientation,
            squareStyles: highlight,
            darkSquareStyle: { backgroundColor: "var(--color-board-dark)" },
            lightSquareStyle: { backgroundColor: "var(--color-board-light)" },
            darkSquareNotationStyle: { color: "var(--color-board-light)", fontWeight: 600, opacity: 0.85 },
            lightSquareNotationStyle: { color: "var(--color-board-dark)", fontWeight: 600 },
            arrows: arrows.map((a) => ({ startSquare: a.uci.slice(0, 2), endSquare: a.uci.slice(2, 4), color: ARROW[a.kind] })),
            arrowOptions: { ...defaultArrowOptions, arrowWidthDenominator: 9, opacity: 0.85, arrowLengthReducerDenominator: 6 },
            allowDrawingArrows: false,
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
    </div>
  );
}
