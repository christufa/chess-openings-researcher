import { useMemo, useState } from "react";
import type { Opening } from "../api";

interface Props {
  openings: Opening[];
  onPick: (opening: Opening) => void;
}

export function OpeningSearch({ openings, onPick }: Props) {
  const [query, setQuery] = useState("");
  const [focused, setFocused] = useState(false);
  const matches = useMemo(
    () => openings.filter((o) => o.opening.toLowerCase().includes(query.trim().toLowerCase())).slice(0, 8),
    [openings, query],
  );
  return (
    <div className="relative w-64">
      <input
        className="h-9 w-full rounded-md border border-line bg-panel px-3 text-sm text-strong placeholder:text-muted focus:border-accent focus:outline-none"
        placeholder="Jump to an opening"
        aria-label="Jump to an opening"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setTimeout(() => setFocused(false), 150)}
      />
      {focused && matches.length > 0 && (
        <ul className="absolute z-10 mt-1 w-full overflow-hidden rounded-md border border-line bg-raised shadow-lg">
          {matches.map((o) => (
            <li key={o.opening_id}>
              <button className="w-full px-3 py-2 text-left text-sm hover:bg-panel" onMouseDown={() => { onPick(o); setQuery(""); }}>
                {o.opening}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
