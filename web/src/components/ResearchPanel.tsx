import { useEffect, useRef, useState } from "react";
import { api, type Claim, type Evidence, type Opening, type TreePosition } from "../api";

const CATEGORY_COLORS: Record<string, string> = {
  plan: "bg-accent/15 text-accent",
  tactic: "bg-poor/15 text-poor",
  pawn_structure: "bg-book/15 text-book",
  move_order: "bg-weaker/15 text-weaker",
};

interface Props {
  position?: TreePosition;
  openings: Opening[];
}

/** What the research says about the openings passing through this position. */
export function ResearchPanel({ position, openings }: Props) {
  const names = position?.openings ?? [];
  const runs = openings.filter((o) => names.includes(o.opening));
  const [claims, setClaims] = useState<Record<string, Claim[]>>({});
  const [open, setOpen] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Record<string, Evidence[]>>({});
  const requested = useRef(new Set<string>()); // in flight or done: never fetch a run twice
  const runKey = runs.length <= 3 ? runs.map((r) => r.run_id).join(",") : "";

  useEffect(() => {
    for (const runId of runKey ? runKey.split(",") : []) {
      if (requested.current.has(runId)) continue;
      requested.current.add(runId);
      api.claims(runId).then((items) => setClaims((c) => ({ ...c, [runId]: items }))).catch(() => requested.current.delete(runId));
    }
  }, [runKey]);

  if (!position) return null;
  if (!runs.length) {
    return (
      <p className="text-sm text-muted">
        {position.in_reference
          ? "A named variation, but no researched opening reaches this position yet."
          : "Out of book here: no researched opening reaches this position."}
      </p>
    );
  }
  if (runs.length > 3) {
    return (
      <p className="text-sm text-muted">
        {runs.length} researched openings continue from here. Play on, or jump to one, to see what the research says.
      </p>
    );
  }
  const toggle = (runId: string, claim: Claim) => {
    const key = `${runId}/${claim.candidate_id}`;
    setOpen(open === key ? null : key);
    if (!evidence[key]) api.evidence(runId, claim.candidate_id).then((items) => setEvidence((e) => ({ ...e, [key]: items })));
  };
  return (
    <div className="space-y-4">
      {runs.slice(0, 3).map((run) => (
        <section key={run.run_id}>
          <h3 className="mb-2 text-sm font-medium text-strong">{run.opening}</h3>
          <ul className="space-y-2">
            {(claims[run.run_id] ?? []).map((claim) => {
              const key = `${run.run_id}/${claim.candidate_id}`;
              return (
                <li key={claim.candidate_id} className="rounded-md border border-line bg-panel p-2 text-sm">
                  <button className="w-full text-left" onClick={() => toggle(run.run_id, claim)}>
                    <span className={`mr-2 rounded px-1.5 py-0.5 text-[11px] ${CATEGORY_COLORS[claim.category] ?? "bg-raised text-muted"}`}>
                      {claim.category.replace("_", " ")}
                    </span>
                    {claim.side && <span className="mr-1 text-[11px] text-muted">{claim.side}</span>}
                    {claim.text}
                  </button>
                  {open === key && (
                    <ul className="mt-2 space-y-1 border-t border-line pt-2 text-xs text-muted">
                      {(evidence[key] ?? []).map((e, i) => (
                        <li key={i}>
                          <q className="text-text">{e.excerpt.slice(0, 240)}{e.excerpt.length > 240 ? "…" : ""}</q>{" "}
                          <a className="text-accent hover:underline" href={e.url} target="_blank" rel="noreferrer noopener">
                            {new URL(e.url).hostname}
                          </a>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
      <p className="text-[11px] text-muted">Claims are model-reviewed against their cited sources, not human-verified.</p>
    </div>
  );
}
