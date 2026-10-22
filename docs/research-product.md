# Structured opening encyclopedia

The first product is a cited encyclopedia of openings and positions. Repertoire
recommendations and engine analysis are later products. A successful model call
is not proof that an opening has been researched thoroughly.

## Research contract

Each research unit identifies a canonical opening or variation, aliases and ECO
codes where supported, a legal move sequence, and a canonical position. Store
move-order paths separately from positions so transpositions share knowledge
without losing their history. Attach claims to the applicable position or line,
side, conditions and source evidence; do not generalize a line-specific claim
to the entire opening.

Cover plans for both sides, pawn structures and breaks, piece placement,
maneuvers, tactical themes, common mistakes, move-order subtleties, assessments
and resulting endgames. Every topic can explicitly be unknown or not applicable.
Assessments must retain their author/date/context. Web claims, observed game
statistics and engine evaluations are separate evidence types, never interchangeable.

## Repeatable workflow

1. Select a canonical variation and an explicit branch/position coverage target.
2. Collect targeted sources for missing topics and branches. Preserve fetch time,
   URL, content hash and evidence excerpts under a documented retention policy.
3. Extract constrained candidates. Treat retrieved text as data, never agent
   instructions. Agents cannot publish directly or access deployment credentials.
4. Validate chess legality, canonical identities, evidence references, exact
   excerpt support and schema constraints deterministically.
5. Review claim support and scope. Record independent corroboration, copied-source
   relationships, contradictions and unresolved disagreements. Model agreement
   alone does not establish truth or source independence.
6. Publish accepted facts under a completed-run boundary. Preserve rejected and
   unresolved candidates privately for review. Re-running must be idempotent.
7. Compare coverage and quality to a curated benchmark before expanding the batch.

## Durable knowledge and agent replacement

Agents produce versioned candidate contracts. Record model, prompt, code and
contract versions alongside collection and review provenance. Replacing an agent
must not require replacing canonical identities or deleting prior research.

The intended library is cumulative: explicit additions, contradictions,
supersessions and retractions create an auditable history. A new run must not
silently erase a previously supported claim. The currently implemented pipeline
still publishes replacement snapshots per opening; cumulative reconciliation,
canonical variation registry and branch-directed collection are implementation
milestones, not existing capabilities.

## Acceptance criteria

- All published move sequences replay legally and resolve to their stored positions.
- All published claims have traceable supporting excerpts and review decisions.
- Coverage denominators come from explicit curated branch/topic targets; counts
  of claims or searched pages are not completeness scores.
- A small adjudicated benchmark measures unsupported claims, wrong scope,
  duplicate claims, missed contradictions and coverage before a larger rollout.
- Fixture runs, retries and alternate agents preserve identity and provenance.
- Public browsing excludes provider responses, credentials, private review notes
  and operational details. Private scheduling and publication use authenticated,
  authorized paths with audit logs.

The existing 20-opening batch is an initial collection pass. It is not a claim
that those 20 openings have complete or authoritative encyclopedia entries.
