import { useEffect, useMemo, useState } from "react";
import { api, type NamedLine, type Opening } from "../api";

interface Props {
  openings: Opening[];
  onPick: (movesUci: string[]) => void;
}

/** Researched openings first, then named variations from the reference book (by name or ECO). */
export function OpeningSearch({ openings, onPick }: Props) {
  const [query, setQuery] = useState("");
  const [focused, setFocused] = useState(false);
  const [named, setNamed] = useState<NamedLine[]>([]);
  const q = query.trim();
  const researched = useMemo(
    () => (q ? openings.filter((o) => o.opening.toLowerCase().includes(q.toLowerCase())).slice(0, 4) : []),
    [openings, q],
  );

  useEffect(() => {
    if (q.length < 2) return setNamed([]);
    let stale = false;
    const timer = setTimeout(() => {
      api.names(q).then((items) => !stale && setNamed(items)).catch(() => undefined);
    }, 200);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [q]);

  /** A researched opening: walk its shortest researched line. */
  const pickOpening = async (opening: Opening) => {
    const lines = await api.lines(opening.run_id);
    if (lines.length) onPick(lines.reduce((a, b) => (b.moves_uci.length < a.moves_uci.length ? b : a)).moves_uci);
  };
  const done = () => setQuery("");

  return (
    <div className="relative w-72">
      <input
        className="h-9 w-full rounded-md border border-line bg-panel px-3 text-sm text-strong placeholder:text-muted focus:border-accent focus:outline-none"
        placeholder="Jump to an opening or ECO code"
        aria-label="Jump to an opening"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setTimeout(() => setFocused(false), 150)}
      />
      {focused && researched.length + named.length > 0 && (
        <ul className="absolute z-10 mt-1 max-h-96 w-full overflow-y-auto rounded-md border border-line bg-raised shadow-lg">
          {researched.map((o) => (
            <li key={o.opening_id}>
              <button className="w-full px-3 py-2 text-left text-sm hover:bg-panel" onMouseDown={() => { void pickOpening(o); done(); }}>
                <span className="mr-2 text-[10px] uppercase tracking-wide text-book">researched</span>
                {o.opening}
              </button>
            </li>
          ))}
          {named.map((v) => (
            <li key={`${v.eco} ${v.name}`}>
              <button className="w-full px-3 py-2 text-left text-sm hover:bg-panel" onMouseDown={() => { onPick(v.moves_uci); done(); }}>
                <span className="mr-2 font-mono text-[11px] text-reference">{v.eco}</span>
                {v.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
