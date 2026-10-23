import { describe, expect, it } from "vitest";
import type { TreeMove, TreePosition } from "./api";
import { emptyTree, layout, openingName, pathTo, ROOT, scoreLabel, visibleChildren, withPosition } from "./model";

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -";

function move(uci: string, san: string, quality: TreeMove["quality"], extra: Partial<TreeMove> = {}): TreeMove {
  return { uci, san, book: quality === "book", fen: `${uci}-fen`, openings: [], lines: [], continues: false,
    quality, engine_quality: null, score_cp: null, mate: null, loss_cp: null, ...extra };
}

function position(moves: TreeMove[], names: string[] = []): TreePosition {
  return { position_id: "p", fen: START, side_to_move: "white", in_book: true, names, openings: [],
    evaluated: false, engine: null, moves };
}

describe("tree model", () => {
  const tree = withPosition(emptyTree(START), ROOT, position([
    move("e2e4", "e4", "book"), move("d2d4", "d4", "book"), move("g2g4", "g4", "poor"),
  ]));

  it("adds a child per move, keyed by the move path", () => {
    expect(tree[ROOT].children).toEqual(["e2e4", "d2d4", "g2g4"]);
    expect(tree["e2e4"]).toMatchObject({ parent: ROOT, ply: 1, fen: "e2e4-fen" });
    const deeper = withPosition(tree, "e2e4", position([move("e7e5", "e5", "book")], ["King's Pawn"]));
    expect(deeper["e2e4 e7e5"].parent).toBe("e2e4");
    expect(pathTo("e2e4 e7e5")).toEqual([ROOT, "e2e4", "e2e4 e7e5"]);
    expect(openingName(deeper, "e2e4 e7e5")).toBe("King's Pawn");
    expect(openingName(tree, ROOT)).toBe(""); // every opening passes the start: no name
  });

  it("hides weaker and poor moves unless asked, or unless they are on the current path", () => {
    expect(visibleChildren(tree, ROOT, false, new Set()).map((n) => n.id)).toEqual(["e2e4", "d2d4"]);
    expect(visibleChildren(tree, ROOT, true, new Set())).toHaveLength(3);
    expect(visibleChildren(tree, ROOT, false, new Set(["g2g4"]))).toHaveLength(3);
  });

  it("lays out only the visible tree, top-down", () => {
    const placed = layout(tree, false, ROOT);
    expect(placed.map((p) => p.node.id).sort()).toEqual(["", "d2d4", "e2e4"]);
    const root = placed.find((p) => p.node.id === ROOT)!;
    expect(placed.every((p) => p.node.id === ROOT || p.y > root.y)).toBe(true);
  });

  it("shows scores from White's side", () => {
    const white = { id: "e2e4", parent: ROOT, ply: 1, fen: "", move: move("e2e4", "e4", "book", { score_cp: 30 }) };
    const black = { id: "e2e4 c7c5", parent: "e2e4", ply: 2, fen: "", move: move("c7c5", "c5", "book", { score_cp: 25 }) };
    const mated = { ...black, move: move("g7g5", "g5", "poor", { mate: -2 }) };
    expect([scoreLabel(white), scoreLabel(black), scoreLabel(mated)]).toEqual(["+0.3", "-0.3", "#2"]);
  });
});
