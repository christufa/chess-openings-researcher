import { ReactFlowProvider } from "@xyflow/react";
import { Chess } from "chess.js";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, fullFen, type Opening, type TreeMove } from "./api";
import { Board } from "./components/Board";
import { BookIcon } from "./components/BookIcon";
import { OpeningSearch } from "./components/OpeningSearch";
import { ResearchPanel } from "./components/ResearchPanel";
import { TreeView } from "./components/TreeView";
import { childId, emptyTree, openingName, pathTo, ROOT, type Tree, visibleChildren, withPosition } from "./model";

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -";

export default function App() {
  const [tree, setTree] = useState<Tree>(() => emptyTree(START));
  const [current, setCurrent] = useState(ROOT);
  const [showWeaker, setShowWeaker] = useState(false);
  const [focus, setFocus] = useState(false);
  const [orientation, setOrientation] = useState<"white" | "black">("white");
  const [openings, setOpenings] = useState<Opening[]>([]);
  const [error, setError] = useState("");
  const treeRef = useRef(tree);
  treeRef.current = tree;

  /** Fetches a node's position and children once; returns the updated tree. */
  const load = useCallback(async (id: string): Promise<Tree> => {
    const node = treeRef.current[id];
    if (!node || node.children) return treeRef.current;
    try {
      const position = await api.tree(id === ROOT ? undefined : node.fen);
      const next = withPosition(treeRef.current, id, position);
      treeRef.current = next;
      setTree(next);
      setError("");
      return next;
    } catch {
      setError("The research service is not answering. Try again in a moment.");
      return treeRef.current;
    }
  }, []);

  const select = useCallback(
    (id: string) => {
      setCurrent(id);
      void load(id);
    },
    [load],
  );

  useEffect(() => {
    void load(ROOT);
    api
      .openings()
      .then((items) => setOpenings(items.filter((o) => !o.opening.startsWith("__"))))
      .catch(() => undefined);
  }, [load]);

  /** A move from the board: follow the tree if it is there, else add an explored node. */
  const play = useCallback(
    (uci: string) => {
      const node = treeRef.current[current];
      const id = childId(current, uci);
      if (treeRef.current[id]) return select(id);
      const game = new Chess(fullFen(node.fen));
      const made = game.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] ?? "q" });
      const fen = game.fen().split(" ").slice(0, 4).join(" ");
      const move: TreeMove = {
        uci, san: made.san, book: false, reference: false, fen, openings: [], lines: [], continues: false,
        quality: "explored", engine_quality: null, score_cp: null, mate: null, loss_cp: null,
      };
      const next: Tree = {
        ...treeRef.current,
        [current]: { ...node, children: [...(node.children ?? []), id] },
        [id]: { id, parent: current, ply: node.ply + 1, fen, move },
      };
      treeRef.current = next;
      setTree(next);
      select(id);
    },
    [current, select],
  );

  /** Jump along a line of moves from the start, loading each step. */
  const jump = useCallback(
    async (movesUci: string[]) => {
      let id = ROOT;
      for (const uci of movesUci) {
        const loaded = await load(id);
        const next = childId(id, uci);
        if (!loaded[next]) break;
        id = next;
      }
      select(id);
    },
    [load, select],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      const t = treeRef.current;
      const node = t[current];
      const path = new Set(pathTo(current));
      if (e.key === "ArrowUp" && node.parent !== null) select(node.parent);
      else if (e.key === "ArrowDown") {
        const first = visibleChildren(t, current, showWeaker, path)[0];
        if (first) select(first.id);
      } else if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && node.parent !== null) {
        const siblings = visibleChildren(t, node.parent, showWeaker, path);
        const i = siblings.findIndex((s) => s.id === current) + (e.key === "ArrowLeft" ? -1 : 1);
        if (siblings[i]) select(siblings[i].id);
      } else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, showWeaker, select]);

  const node = tree[current];
  const moves = pathTo(current)
    .slice(1)
    .map((id) => tree[id]);
  const name = openingName(tree, current);

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2">
        <h1 className="text-base font-medium text-strong">Openings research</h1>
        <nav className="min-w-0 flex-1 truncate text-sm text-muted" aria-label="Current line">
          {name.eco && <span className="mr-1.5 font-mono text-xs text-reference">{name.eco}</span>}
          {name.name && <span className="mr-2 text-strong">{name.name}</span>}
          <span className="font-mono">
            {moves.map((m, i) => (
              <button key={m.id} className="mr-1 hover:text-strong" onClick={() => select(m.id)}>
                {i % 2 === 0 ? `${i / 2 + 1}.` : ""}
                {m.move?.san}
              </button>
            ))}
          </span>
        </nav>
        <OpeningSearch openings={openings} onPick={(moves) => void jump(moves)} />
        <label className="flex items-center gap-2 text-sm" title="Weaker moves and named sidelines">
          <input type="checkbox" checked={showWeaker} onChange={(e) => setShowWeaker(e.target.checked)} />
          More moves
        </label>
        <button
          className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-panel"
          onClick={() => setFocus(!focus)}
        >
          {focus ? "Show research" : "Focus"}
        </button>
      </header>
      {error && <p className="bg-poor/15 px-4 py-2 text-sm text-poor">{error}</p>}
      {/* Narrow screens scroll the page (board, then tree, then research); wide ones split it. */}
      <main className="grid flex-1 grid-cols-1 overflow-y-auto lg:min-h-0 lg:grid-cols-[minmax(320px,560px)_1fr] lg:overflow-hidden">
        <section className="border-line p-4 lg:min-h-0 lg:overflow-y-auto lg:border-r">
          <Board fen={node.fen} lastMove={node.move?.uci} orientation={orientation} onMove={play} />
          <div className="mt-2 flex items-center justify-between text-xs text-muted">
            <span>
              {node.position?.engine
                ? `${node.position.engine.name} ${node.position.engine.version}, depth ${node.position.engine.depth}`
                : "No engine evaluation for this position yet"}
            </span>
            <button
              className="hover:text-strong"
              onClick={() => setOrientation(orientation === "white" ? "black" : "white")}
            >
              Flip board
            </button>
          </div>
          {!focus && (
            <div className="mt-4">
              <ResearchPanel position={node.position} openings={openings} />
            </div>
          )}
        </section>
        <section className="relative h-[60vh] border-t border-line lg:h-auto lg:min-h-0 lg:border-t-0" aria-label="Move tree">
          <ReactFlowProvider>
            <TreeView tree={tree} current={current} showWeaker={showWeaker} onSelect={select} />
          </ReactFlowProvider>
          <div className="pointer-events-none absolute bottom-3 left-3 flex gap-3 rounded-md bg-page/80 px-2 py-1 text-[11px] text-muted">
            <span>
              <BookIcon className="text-book" /> book
            </span>
            <span className="text-reference">named</span>
            <span className="text-weaker">- - weaker</span>
            <span className="text-poor">- - poor</span>
            <span className="hidden lg:inline">arrow keys move through the tree</span>
          </div>
        </section>
      </main>
    </div>
  );
}
