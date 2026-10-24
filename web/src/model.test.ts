import { describe, expect, it } from "vitest";
import type { TreeMove, TreePosition } from "./api";
import { emptyTree, layout, openingName, pathTo, ROOT, scoreLabel, visibleChildren, withPosition } from "./model";

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -";

function move(uci: string, san: string, quality: TreeMove["quality"], extra: Partial<TreeMove> = {}): TreeMove {
  return { uci, san, book: quality === "book", reference: quality === "reference", variations: 0, fen: `${uci}-fen`, openings: [], lines: [], continues: false,
    quality, engine_quality: null, score_cp: null, mate: null, loss_cp: null, ...extra };
}

function position(moves: TreeMove[], names: string[] = [], extra: Partial<TreePosition> = {}): TreePosition {
  return { position_id: "p", fen: START, side_to_move: "white", in_book: true, in_reference: false, names,
    reference: [], openings: [], evaluated: false, engine: null, moves, ...extra };
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
    expect(openingName(deeper, "e2e4 e7e5")).toEqual({ name: "King's Pawn" });
    expect(openingName(tree, ROOT)).toEqual({ name: "" }); // every opening passes the start: no name
    const named = withPosition(deeper, "e2e4 e7e5", position([], ["Researched name"], {
      reference: [{ eco: "C20", name: "King's Pawn Game" }] }));
    expect(openingName(named, "e2e4 e7e5")).toEqual({ eco: "C20", name: "King's Pawn Game" }); // the standard name wins
  });

  it("hides weaker and poor moves unless asked, or unless they are on the current path", () => {
    expect(visibleChildren(tree, ROOT, false, new Set()).map((n) => n.id)).toEqual(["e2e4", "d2d4"]);
    expect(visibleChildren(tree, ROOT, true, new Set())).toHaveLength(3);
    expect(visibleChildren(tree, ROOT, false, new Set(["g2g4"]))).toHaveLength(3);
  });

  it("shows named sidelines the engine rates good, or all of them where it has not looked", () => {
    const moves = [
      move("e2e4", "e4", "book"),
      move("d2d4", "d4", "reference", { engine_quality: "good" }),
      move("b2b4", "b4", "reference", { engine_quality: "poor" }),
      move("a2a3", "a3", "reference"),
    ];
    const rated = withPosition(emptyTree(START), ROOT, position(moves, [], { evaluated: true }));
    expect(visibleChildren(rated, ROOT, false, new Set()).map((n) => n.id)).toEqual(["e2e4", "d2d4"]);
    expect(visibleChildren(rated, ROOT, true, new Set())).toHaveLength(4);
    const unrated = withPosition(emptyTree(START), ROOT, position(moves));
    expect(visibleChildren(unrated, ROOT, false, new Set()).map((n) => n.id)).toEqual(["e2e4", "d2d4", "a2a3"]);
    // Unrated, only the named moves most variations go through show by default.
    const many = ["a2a3", "b2b3", "c2c3", "d2d3", "f2f3", "g2g3"].map((uci, i) => move(uci, uci, "reference", { variations: i }));
    const wide = withPosition(emptyTree(START), ROOT, position(many));
    expect(visibleChildren(wide, ROOT, false, new Set()).map((n) => n.id)).toEqual(["c2c3", "d2d3", "f2f3", "g2g3"]);
    expect(visibleChildren(wide, ROOT, true, new Set())).toHaveLength(6);
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

describe("evaluation", () => {
  it("takes the best rated move, from White's side", async () => {
    const { positionEval, evalShare } = await import("./model");
    const moves = [
      move("e7e5", "e5", "book", { score_cp: -20, loss_cp: 10 }),
      move("c7c5", "c5", "book", { score_cp: -10, loss_cp: 0 }),
      move("a7a5", "a5", "reference"),
    ];
    const black = position(moves, [], { side_to_move: "black", evaluated: true });
    expect(positionEval(black)).toEqual({ cp: 10, mate: null }); // Black's -10 is White's +10
    expect(positionEval(position([move("e2e4", "e4", "book")]))).toBeNull();
    expect(evalShare(null)).toBe(0.5);
    expect(evalShare({ cp: null, mate: 3 })).toBe(1);
    expect(evalShare({ cp: 400, mate: null })).toBeGreaterThan(0.85);
  });
});
