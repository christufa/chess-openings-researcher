// The explorer API (src/openings_research/api.py). Read-only and rate-limited per client.

// "reference": a named variation (the reference book) that no research covers yet.
// "explored" is client-only: a move played on the board that neither the book nor the engine offered.
export type Quality = "book" | "reference" | "good" | "weaker" | "poor" | "explored";

export interface TreeMove {
  uci: string;
  san: string;
  book: boolean; // researched lines play it
  reference: boolean; // a named variation plays it
  variations: number; // named variations through it
  fen: string;
  openings: string[];
  lines: string[];
  continues: boolean;
  quality: Quality;
  engine_quality: "good" | "weaker" | "poor" | null;
  score_cp: number | null;
  mate: number | null;
  loss_cp: number | null;
}

export interface TreePosition {
  position_id: string;
  fen: string;
  side_to_move: "white" | "black";
  in_book: boolean;
  in_reference: boolean;
  names: string[]; // researched lines ending here
  reference: Variation[]; // named variations ending here
  openings: string[];
  evaluated: boolean;
  engine: { name: string; version: string; depth: number } | null;
  moves: TreeMove[];
}

export interface Variation {
  eco: string;
  name: string;
}

export interface NamedLine extends Variation {
  moves_uci: string[];
}

export interface Opening {
  opening_id: string;
  opening: string;
  run_id: string;
}

export interface Claim {
  candidate_id: string;
  text: string;
  category: string;
  side: string | null;
}

export interface Line {
  name: string;
  moves_uci: string[];
}

export interface Evidence {
  url: string;
  title: string | null;
  excerpt: string;
  relation: string;
}

async function get<T>(path: string): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    const response = await fetch(path, { headers: { Accept: "application/json" } });
    if (response.status === 429 && attempt < 3) {
      const wait = Number(response.headers.get("Retry-After") ?? "1");
      await new Promise((resolve) => setTimeout(resolve, wait * 1000));
      continue;
    }
    if (!response.ok) throw new Error(`${response.status} ${path}`);
    return (await response.json()) as T;
  }
}

/** The API takes a full FEN; the tree's FENs omit the move counters. */
export const fullFen = (fen: string) => (fen.split(" ").length === 4 ? `${fen} 0 1` : fen);

export const api = {
  tree: (fen?: string) =>
    get<TreePosition>(fen ? `/api/v1/tree?fen=${encodeURIComponent(fullFen(fen))}` : "/api/v1/tree"),
  names: (q: string) =>
    get<{ items: NamedLine[] }>(`/api/v1/names?q=${encodeURIComponent(q)}&limit=30`).then((r) => r.items),
  openings: () => get<{ items: Opening[] }>("/api/v1/openings?limit=100").then((r) => r.items),
  claims: (runId: string) =>
    get<{ items: Claim[] }>(`/api/v1/runs/${encodeURIComponent(runId)}/claims?limit=100`).then((r) => r.items),
  lines: (runId: string) =>
    get<{ items: Line[] }>(`/api/v1/runs/${encodeURIComponent(runId)}/lines?limit=100`).then((r) => r.items),
  evidence: (runId: string, candidateId: string) =>
    get<{ items: Evidence[] }>(
      `/api/v1/runs/${encodeURIComponent(runId)}/evidence/${encodeURIComponent(candidateId)}`,
    ).then((r) => r.items),
};
