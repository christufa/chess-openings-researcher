import { ReactFlowProvider } from "@xyflow/react";
import { Chess } from "chess.js";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, fullFen, type Opening, type TreeMove } from "./api";
import { Board, type BoardArrow, evalText } from "./components/Board";
import { GoTo } from "./components/GoTo";
import { ResearchPanel } from "./components/ResearchPanel";
import { TreeView } from "./components/TreeView";
import { childId, emptyTree, openingName, pathTo, positionEval, ROOT, type Tree, visibleChildren, withPosition } from "./model";

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -";

export default function App() {
  const [tree, setTree] = useState<Tree>(() => emptyTree(START));
  const [current, setCurrent] = useState(ROOT);
  const [showWeaker, setShowWeaker] = useState(false);
  const [focus, setFocus] = useState(false);
  const [palette, setPalette] = useState(false);
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
        uci, san: made.san, book: false, reference: false, variations: 0, fen, openings: [], lines: [], continues: false,
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
      if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !(e.target instanceof HTMLInputElement))) {
        e.preventDefault();
        setPalette(true);
        return;
      }
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
  const evaluation = positionEval(node.position);
  const arrows: BoardArrow[] = visibleChildren(tree, current, showWeaker, new Set())
    .filter((c) => c.move && c.move.quality !== "explored")
    .slice(0, 4)
    .map((c) => ({ uci: c.move!.uci, kind: c.move!.book ? "book" : c.move!.quality === "reference" ? "reference" : "engine" }));
  const engine = node.position?.engine;

  return (
    <div className="flex h-full flex-col">
      <header className="z-20 flex items-center gap-3 border-b border-line/70 bg-page/70 px-4 py-2.5 backdrop-blur">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-accent to-reference text-sm text-white shadow-lg shadow-accent/20" aria-hidden>
            ♞
          </span>
          <h1 className="hidden text-[15px] font-semibold tracking-tight text-strong sm:block">Openings</h1>
        </div>
        <button
          className="mx-auto flex h-9 w-full max-w-md items-center gap-2 rounded-xl border border-line bg-panel/80 px-3 text-sm text-muted transition hover:border-accent/50 hover:text-text"
          onClick={() => setPalette(true)}
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
          </svg>
          <span className="flex-1 truncate text-left">Go to an opening…</span>
          <kbd className="hidden rounded border border-line px-1.5 text-[10px] sm:inline">Ctrl K</kbd>
        </button>
        <div className="flex rounded-xl border border-line bg-panel/80 p-0.5 text-xs" role="group" aria-label="Moves shown">
          {[false, true].map((all) => (
            <button
              key={String(all)}
              aria-pressed={showWeaker === all}
              title={all ? "Also weaker moves and named sidelines" : "Book and good moves"}
              className={`whitespace-nowrap rounded-lg px-2.5 py-1.5 transition ${showWeaker === all ? "bg-raised text-strong shadow" : "text-muted hover:text-text"}`}
              onClick={() => setShowWeaker(all)}
            >
              {all ? "All moves" : "Main"}
            </button>
          ))}
        </div>
        <button
          className={`hidden rounded-xl border border-line px-3 py-1.5 text-xs transition sm:block ${focus ? "bg-raised text-strong" : "bg-panel/80 text-muted hover:text-text"}`}
          aria-pressed={focus}
          onClick={() => setFocus(!focus)}
        >
          Focus
        </button>
      </header>
      {error && <p className="bg-poor/15 px-4 py-2 text-sm text-poor">{error}</p>}
      {/* Narrow screens scroll the page (board, then tree, then research); wide ones split it. */}
      <main className="grid flex-1 grid-cols-1 overflow-y-auto lg:min-h-0 lg:grid-cols-[minmax(340px,580px)_1fr] lg:overflow-hidden">
        <section className="space-y-4 p-4 lg:min-h-0 lg:overflow-y-auto">
          <nav className="rounded-2xl border border-line bg-panel/70 p-3" aria-label="Current line">
            <div className="flex min-h-6 items-center gap-2">
              {name.eco && <span className="rounded-md bg-reference/15 px-1.5 py-0.5 font-mono text-[11px] text-reference">{name.eco}</span>}
              <span className="truncate text-[15px] font-medium text-strong">{name.name || "Starting position"}</span>
            </div>
            {moves.length === 0 && <p className="mt-1.5 text-xs text-muted">Play a move on the board, or pick one in the tree.</p>}
            <div className="mt-2 flex flex-wrap gap-1 font-mono text-[12px] empty:hidden">
              {moves.map((m, i) => (
                <button
                  key={m.id}
                  className={`rounded-md px-1.5 py-0.5 transition ${m.id === current ? "bg-accent/20 text-strong" : "text-muted hover:bg-raised hover:text-text"}`}
                  onClick={() => select(m.id)}
                >
                  {i % 2 === 0 && <span className="mr-0.5 text-muted/70">{i / 2 + 1}.</span>}
                  {m.move?.san}
                </button>
              ))}
            </div>
          </nav>
          <Board fen={node.fen} lastMove={node.move?.uci} orientation={orientation} arrows={arrows} evaluation={evaluation} onMove={play} />
          <div className="flex items-center gap-3 px-5 text-xs text-muted">
            {evaluation && <span className="rounded-md bg-raised px-1.5 py-0.5 font-mono text-text">{evalText(evaluation)}</span>}
            <span className="flex-1 truncate">
              {engine ? `${engine.name} ${engine.version} · depth ${engine.depth}` : "No engine evaluation for this position yet"}
            </span>
            <button
              className="rounded-md px-2 py-1 hover:bg-raised hover:text-strong"
              onClick={() => node.parent !== null && select(node.parent)}
              disabled={node.parent === null}
              aria-label="Previous move"
            >
              ←
            </button>
            <button className="rounded-md px-2 py-1 hover:bg-raised hover:text-strong" onClick={() => setOrientation(orientation === "white" ? "black" : "white")}>
              Flip
            </button>
          </div>
          {!focus && (
            <div className="rounded-2xl border border-line bg-panel/70 p-4">
              <ResearchPanel position={node.position} openings={openings} />
            </div>
          )}
        </section>
        <section className="relative h-[60vh] border-t border-line lg:h-auto lg:min-h-0 lg:border-t-0 lg:border-l" aria-label="Move tree">
          <ReactFlowProvider>
            <TreeView tree={tree} current={current} showWeaker={showWeaker} onSelect={select} />
          </ReactFlowProvider>
          <div className="pointer-events-none absolute left-3 top-3 flex flex-wrap items-center gap-3 rounded-xl border border-line bg-panel/80 px-3 py-1.5 text-[11px] text-muted backdrop-blur">
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-book" />book</span>
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-reference" />named</span>
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-accent" />engine</span>
            <span className="flex items-center gap-1.5"><span className="h-0 w-3 border-t border-dashed border-weaker" />weaker</span>
            <span className="flex items-center gap-1.5"><span className="h-0 w-3 border-t border-dashed border-poor" />poor</span>
            <span className="hidden lg:inline">· arrow keys to move</span>
          </div>
        </section>
      </main>
      <GoTo open={palette} openings={openings} onClose={() => setPalette(false)} onPick={(m) => void jump(m)} />
    </div>
  );
}
