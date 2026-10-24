// The explored tree, by move order: a node per path of moves from the start. Children load
// lazily from /api/v1/tree when a node is first visited. Pure functions, so they're testable.
import { hierarchy, tree as tidyTree } from "d3-hierarchy";
import type { Quality, TreeMove, TreePosition } from "./api";

export interface TreeNode {
  id: string; // the moves from the start, space-separated UCI ("" is the start)
  parent: string | null;
  ply: number;
  fen: string;
  move?: TreeMove; // the move that reached this node
  children?: string[]; // undefined until loaded
  position?: TreePosition;
}

export type Tree = Record<string, TreeNode>;

export const ROOT = "";

export const childId = (parent: string, uci: string) => (parent ? `${parent} ${uci}` : uci);

export function emptyTree(startFen: string): Tree {
  return { [ROOT]: { id: ROOT, parent: null, ply: 0, fen: startFen } };
}

/** Records a fetched position for a node and adds a child per move (keeps existing ones). */
export function withPosition(tree: Tree, id: string, position: TreePosition): Tree {
  const node = tree[id];
  const next: Tree = { ...tree, [id]: { ...node, position, children: position.moves.map((m) => childId(id, m.uci)) } };
  for (const move of position.moves) {
    const cid = childId(id, move.uci);
    next[cid] = next[cid] ? { ...next[cid], move } : { id: cid, parent: id, ply: node.ply + 1, fen: move.fen, move };
  }
  return next;
}

const SHOWN: Record<Quality, boolean> = { book: true, reference: true, good: true, weaker: false, poor: false, explored: true };

export const UNRATED_NAMED_SHOWN = 4;

/** Whether a move shows without "All moves": researched and good ones always; named
 *  variations when the engine rates them good, or, where it has not looked at the position,
 *  the few that most named variations go through (it rates its top moves only, so an unrated
 *  sideline of a rated position is not among them). */
function shown(move: TreeMove, parent: TreePosition | undefined, busiest: Set<string>): boolean {
  if (move.quality !== "reference") return SHOWN[move.quality];
  if (move.engine_quality !== null) return move.engine_quality === "good";
  return !parent?.evaluated && busiest.has(move.uci);
}

/** Book and good moves always; weaker ones and sidelines only when asked for (or when on the path). */
export function visibleChildren(tree: Tree, id: string, showWeaker: boolean, path: Set<string>): TreeNode[] {
  const parent = tree[id]?.position;
  const children = (tree[id]?.children ?? []).map((cid) => tree[cid]).filter(Boolean);
  const busiest = new Set(
    children
      .map((c) => c.move)
      .filter((m): m is TreeMove => m?.quality === "reference" && m.engine_quality === null)
      .sort((a, b) => b.variations - a.variations)
      .slice(0, UNRATED_NAMED_SHOWN)
      .map((m) => m.uci),
  );
  return children.filter((c) => showWeaker || path.has(c.id) || (c.move && shown(c.move, parent, busiest)));
}

/** Node ids from the start to `id`, inclusive. */
export function pathTo(id: string): string[] {
  const moves = id ? id.split(" ") : [];
  return [ROOT, ...moves.map((_, i) => moves.slice(0, i + 1).join(" "))];
}

export interface Placed {
  node: TreeNode;
  x: number;
  y: number;
}

/** Tidy top-down layout of the visible tree. */
export function layout(tree: Tree, showWeaker: boolean, current: string, gap = { x: 84, y: 96 }): Placed[] {
  const path = new Set(pathTo(current));
  const root = hierarchy(tree[ROOT], (n) => visibleChildren(tree, n.id, showWeaker, path));
  tidyTree<TreeNode>().nodeSize([gap.x, gap.y])(root);
  return root.descendants().map((d) => ({ node: d.data, x: d.x ?? 0, y: d.y ?? 0 }));
}

/** The opening name for a node: the deepest position on its path that a named variation
 *  (with its ECO code) or a researched line ends at, or that only one opening passes through. */
export function openingName(tree: Tree, id: string): { name: string; eco?: string } {
  const path = pathTo(id);
  for (let i = path.length - 1; i >= 0; i--) {
    const position = tree[path[i]]?.position;
    if (position?.reference.length) return position.reference[0];
    if (position?.names.length) return { name: position.names[0] };
    if (position?.openings.length === 1) return { name: position.openings[0] };
  }
  return { name: "" };
}

export function moveNumberLabel(node: TreeNode): string {
  if (!node.move) return "";
  const n = Math.ceil(node.ply / 2);
  return node.ply % 2 === 1 ? `${n}.` : `${n}...`;
}

/** The evaluation after the move, from White's side as lichess shows it (the engine scores
 *  for the side that moved, so Black's moves are negated). */
export function scoreLabel(node: TreeNode): string {
  const move = node.move;
  if (!move) return "";
  const sign = node.ply % 2 === 1 ? 1 : -1;
  if (move.mate !== null) return `#${sign * move.mate}`;
  if (move.score_cp === null) return "";
  const pawns = (sign * move.score_cp) / 100;
  return `${pawns > 0 ? "+" : ""}${pawns.toFixed(1)}`;
}

/** The position's evaluation from White's side: the best rated move's score (the engine
 *  scores for the side to move, so Black to move is negated). Null when nothing is rated. */
export function positionEval(position?: TreePosition): { cp: number | null; mate: number | null } | null {
  const best = position?.moves
    .filter((m) => m.loss_cp !== null && (m.score_cp !== null || m.mate !== null))
    .reduce<TreeMove | null>((a, m) => (a === null || (m.loss_cp ?? 0) < (a.loss_cp ?? 0) ? m : a), null);
  if (!position || !best) return null;
  const sign = position.side_to_move === "white" ? 1 : -1;
  return { cp: best.score_cp === null ? null : sign * best.score_cp, mate: best.mate === null ? null : sign * best.mate };
}

/** White's share of the evaluation bar, 0..1 (a smooth curve: ±4 pawns is near the ends). */
export function evalShare(evaluation: { cp: number | null; mate: number | null } | null): number {
  if (!evaluation) return 0.5;
  if (evaluation.mate !== null) return evaluation.mate > 0 ? 1 : 0;
  return 1 / (1 + Math.exp(-(evaluation.cp ?? 0) / 180));
}
