import { Chess } from "chess.js";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type NamedLine, type Opening } from "../api";

interface Props {
  open: boolean;
  openings: Opening[];
  onClose: () => void;
  onPick: (movesUci: string[]) => void;
}

type Item =
  | { kind: "researched"; key: string; title: string; opening: Opening }
  | { kind: "named"; key: string; title: string; eco: string; moves: string; line: NamedLine };

/** "1.e4 c5 2.Nf3 d6" from UCI moves. */
function movetext(movesUci: string[]): string {
  const game = new Chess();
  return movesUci
    .map((uci, i) => {
      const san = game.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] }).san;
      return i % 2 === 0 ? `${i / 2 + 1}.${san}` : san;
    })
    .join(" ");
}

/** A command palette: type an opening, variation or ECO code, pick it, and the board and tree
 *  go there. Researched openings first, then every named variation. */
export function GoTo({ open, openings, onClose, onPick }: Props) {
  const [query, setQuery] = useState("");
  const [named, setNamed] = useState<NamedLine[]>([]);
  const [searching, setSearching] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const q = query.trim();

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      setTimeout(() => input.current?.focus(), 0);
    }
  }, [open]);

  useEffect(() => {
    if (q.length < 2) return setNamed([]);
    let stale = false;
    setSearching(true);
    const timer = setTimeout(
      () =>
        api
          .names(q)
          .then((items) => !stale && setNamed(items))
          .catch(() => undefined)
          .finally(() => !stale && setSearching(false)),
      150,
    );
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [q]);

  const items: Item[] = useMemo(() => {
    const researched = openings
      .filter((o) => o.opening.toLowerCase().includes(q.toLowerCase()))
      .slice(0, q ? 5 : 20)
      .map((o): Item => ({ kind: "researched", key: `r:${o.opening_id}`, title: o.opening, opening: o }));
    // Variations of researched openings first ("Ruy Lopez: Berlin Defense" before "Bishop's
    // Opening: Berlin Defense"); otherwise the API's order, shortest line first.
    const family = new Set(openings.map((o) => o.opening.toLowerCase()));
    const ranked = [...named].sort(
      (a, b) => Number(!family.has(a.name.split(":")[0].toLowerCase())) - Number(!family.has(b.name.split(":")[0].toLowerCase())),
    );
    const variations = ranked.slice(0, 10).map((v): Item => ({
      kind: "named", key: `n:${v.eco}:${v.name}`, title: v.name, eco: v.eco, moves: movetext(v.moves_uci), line: v,
    }));
    return [...researched, ...variations];
  }, [openings, named, q]);

  useEffect(() => setActive(0), [items.length]);

  const choose = async (item: Item | undefined) => {
    if (!item) return;
    onClose();
    if (item.kind === "named") return onPick(item.line.moves_uci);
    const lines = await api.lines(item.opening.run_id);
    if (lines.length) onPick(lines.reduce((a, b) => (b.moves_uci.length < a.moves_uci.length ? b : a)).moves_uci);
  };

  if (!open) return null;
  const firstNamed = items.findIndex((i) => i.kind === "named");
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/55 px-4 pt-[12vh] backdrop-blur-sm" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-label="Go to an opening"
        className="palette-in w-full max-w-xl overflow-hidden rounded-2xl border border-line bg-panel shadow-[0_24px_80px_rgb(0_0_0/0.6)]"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-line px-4">
          <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0 text-muted" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
          </svg>
          <input
            ref={input}
            className="h-14 w-full bg-transparent text-[15px] text-strong placeholder:text-muted focus:outline-none"
            placeholder="Opening, variation or ECO code, e.g. Najdorf, Berlin, B90"
            aria-label="Opening, variation or ECO code"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, items.length - 1));
              else if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
              else if (e.key === "Enter") void choose(items[active]);
              else if (e.key === "Escape") onClose();
              else return;
              e.preventDefault();
            }}
          />
          <kbd className="rounded border border-line px-1.5 py-0.5 text-[10px] text-muted">Esc</kbd>
        </div>
        <ul className="max-h-[52vh] overflow-y-auto p-2" role="listbox">
          {items.length === 0 && (
            <li className="px-3 py-8 text-center text-sm text-muted">
              {q.length < 2 ? "Type at least two letters." : searching ? "Searching…" : "No opening or named variation matches."}
            </li>
          )}
          {items.map((item, i) => (
            <li key={item.key}>
              {(i === 0 || i === firstNamed) && (
                <p className="px-3 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wider text-muted">
                  {item.kind === "researched" ? "Researched openings" : "Named variations"}
                </p>
              )}
              <button
                role="option"
                aria-selected={i === active}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left ${i === active ? "bg-raised" : ""}`}
                onMouseEnter={() => setActive(i)}
                onClick={() => void choose(item)}
              >
                {item.kind === "researched" ? (
                  <span className="h-2 w-2 shrink-0 rounded-full bg-book" aria-hidden />
                ) : (
                  <span className="w-9 shrink-0 rounded bg-reference/15 py-0.5 text-center font-mono text-[11px] text-reference">{item.eco}</span>
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-strong">{item.title}</span>
                  {item.kind === "named" && <span className="block truncate font-mono text-[11px] text-muted">{item.moves}</span>}
                  {item.kind === "researched" && <span className="block text-[11px] text-muted">Researched lines and ideas</span>}
                </span>
                {i === active && <kbd className="text-[10px] text-muted">↵</kbd>}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
