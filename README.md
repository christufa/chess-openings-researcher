# Openings Researcher

A replayable opening-research pipeline that collects web sources, extracts and
validates chess claims, and stores the results in Iceberg on a lean, private Azure
Kubernetes platform. The purpose is data collection: nothing is published to the
internet, and the read-only explorer is reached with `kubectl port-forward`.

Agents produce candidates; the pipeline owns source snapshots, chess validation,
publication, and run history. Game ingestion remains outside this application's scope.

```text
Tavily or saved sources -> collect -> extract -> validate -> review -> publish
                                      |            |         |          |
                              replaceable agent  checks   support   Iceberg tables
```

- [Infrastructure](infra/README.md): Terraform stacks, privacy boundaries, apply order.
- [Deploy](deploy/README.md): Argo CD apps, sync order, first bring-up, access boundaries.
- [Kubernetes runtime](docs/kubernetes.md): Argo batch, Iceberg catalog, explorer.
- [Research contract](docs/research-product.md).

## What works

- One Argo-scheduled worker per opening runs the five stages, with retries and durable stage markers.
- Tavily searches across three topics, deduplicates URLs, and extracts up to six
  documents. Raw responses (including extraction failures) are retained. The agent
  sees up to 10,000 characters per document; the saved source version is that exact
  excerpt, while the raw response retains the full returned text.
- An OpenAI structured-output adapter (configurable model, default `gpt-5.4-mini`; on the
  cluster it calls Azure OpenAI keylessly with the worker's workload identity)
  extracts move sequences, plans, pawn breaks, maneuvers, tactics and assessments.
  It selects numbered source passages; the pipeline copies their original text
  into evidence records. The model does not generate evidence quotations.
- A credential-free fixture adapter exercises the same contracts and tables.
- Legal-move, FEN, source-reference and exact-excerpt validation, followed by a
  separate model review of source support, line naming and claim categories.
  Rejected and ambiguous candidates remain inspectable but are not published.
- Coverage reports across nine topics and both sides, with prioritized gaps and
  suggested searches. Re-extraction receives the parent run's claims and gaps.
- Re-extraction using another model against the exact same saved sources.
- Stable chess entity IDs, idempotent merges, history per run, and current views
  that select only completed publication batches.

## Repository layout

| Location | Purpose |
| --- | --- |
| `src/openings_research/contracts.py` | Versioned Pydantic input/output and position identity |
| `agents.py` | Agent protocol, OpenAI adapter and smoke adapter |
| `evidence.py` | Deterministic passage catalog and source-reference resolution |
| `collectors.py` | Tavily discovery/extraction and request caching |
| `pipeline.py` | Agent-independent orchestration and repair logic |
| `validation.py` | Deterministic chess and evidence checks |
| `review.py`, `taxonomy.py` | Source-support review and explicit claim categories |
| `coverage.py` | Topic/side presence and prioritized research gaps |
| `schema.py`, `storage.py`, `iceberg.py` | Explicit schemas and idempotent Iceberg merges |
| `worker.py`, `api.py`, `serving.py` | Kubernetes worker entry point and read-only explorer |
| `batch.py` | Validates the bounded opening list for an Argo batch |
| `infra/`, `deploy/` | Terraform stacks and Helm charts |
| `.github/workflows/` | Public-repository CI: tests, Terraform, containers, security |
| `tests/` | Identity, evidence, replay, failure recovery and deployment checks |

## Tables and publication

All tables and views use one schema, `openings_research`:

| Tables | Grain / purpose |
| --- | --- |
| `research_runs`, `research_tasks` | Run configuration and stage status |
| `raw_responses` | Cached provider response per request per run |
| `sources`, `source_versions`, `run_sources` | URL identity, captured text and run membership |
| `agent_outputs` | Original structured response, parsed output and token usage |
| `candidate_records`, `validation_results` | Proposed records and mechanical checks |
| `review_outputs`, `candidate_reviews` | Original reviewer response, decisions and rationales |
| `coverage_reports`, `research_gaps` | Publication coverage and suggested follow-up research |
| `openings` | Requested opening identity, normalized by trimmed case-folded name |
| `positions`, `position_moves` | Canonical chess graph |
| `lines`, `opening_lines` | Ordered UCI sequences and named opening associations |
| `claims`, `claim_evidence` | Assertions and source evidence (also used for line candidates) |

Use `current_claims` and `current_lines`, which join `latest_completed_runs`.
Each completed run is a replacement snapshot for that requested opening, not an
incremental union of every historical claim. Compare runs before treating a new
agent as an improvement. New published records must pass both mechanical validation
and review. Their status is `model_reviewed` (or `fixture_reviewed` for the authored
smoke test). A second model pass is not human verification or engine analysis;
both passes use the same default model unless configured otherwise. Historical
records retain their original status. Category corrections preserve the original
candidate and record the reviewer's rationale separately.

`current_coverage` and `current_research_gaps` follow the same completed-run boundary:

```sql
SELECT topic, side, priority, reason, query
FROM research.openings_research.current_research_gaps
ORDER BY priority, topic, side;

SELECT report_json FROM research.openings_research.current_coverage;
```

Coverage measures topic presence, not complete opening theory. It reports branch
completeness and source independence as unassessed. Suggested searches are saved
for follow-up; they do not automatically start additional paid research.

Publication writes all entity tables before marking the run completed. Iceberg
commits are table-scoped; the completed-run view is the publication boundary.
Direct reads of base tables can include partial/unpublished records. An interrupted
publish can be repaired without duplicate keys. No valid candidates means a failed
run, leaving the previous completed run current. Some rejected candidates do not
prevent publishing accepted ones; inspect `validation_results`, `candidate_reviews`
and `coverage_reports` for partial coverage. Missing or duplicate review decisions
block publication. Coverage is persisted before the completed marker as well.

Only this job should write these tables. It allows one concurrent run. Do not
deploy another writer into the same schema. Schema changes require explicit
migrations; `CREATE TABLE IF NOT EXISTS` does not migrate existing tables.

## Position identity / games integration

`position_id` is SHA-256 over a canonical JSON encoding of the identity version
and normalized FEN. Normalized FEN includes piece placement, side to move,
castling rights and **legally available** en passant; move counters are excluded.
The current identity version is `standard-legal-ep-v1`. Only standard chess is
supported. Lines preserve ordered UCI moves separately, so transpositions share
positions without collapsing distinct move orders. Full game history is still
needed for repetition and fifty-move-rule state.

Use the same `position_record()` function when deriving position IDs from the
Lichess games' FENs. This project does not modify or reingest that dataset.

## Adding an agent

Implement `ResearchAgent.extract(ResearchInput) -> Extraction` and register it in
`make_agent()` and the CLI's agent choices. Return `AgentOutput` candidates with
source-version IDs and exact excerpts. Adapters must not write core tables.
Agent configuration, contract/prompt/validator versions and code SHA are recorded
with each run. To add another source type, implement the collector's `collect()`
interface and retain source snapshots. Keep API calls on the driver, outside Spark
UDFs, so Spark task retries cannot silently multiply provider requests.

The OpenAI adapter uses an internal reference schema whose allowed passage IDs
are enumerated for each request. It divides source text into chunks of at most
1,200 characters, preferring paragraph/newline boundaries, and preserves Markdown,
Unicode punctuation and whitespace exactly. Source order is deterministic. A
request with more than 500 passages fails explicitly and must be split rather
than silently losing coverage. Blank sources are ignored.

The adapter resolves passage IDs to the existing `AgentOutput` evidence format;
the evidence contract remains stable. `agent_outputs.raw_response`
now contains a JSON envelope with the original provider response, the evidence-index
version, and passage-to-source offsets (Unicode character offsets, end exclusive).
Old runs retain their original response format. Unknown references fail closed.
The validator still checks exact source membership and legal moves. A matching
passage is traceable evidence, not proof that it supports every assertion; semantic
review is a separate required stage before publication. Review responses and exact
candidate decisions are cached for repair, including malformed review batches
that fail validation. Use a new run to retry a malformed cached review. Prompt,
taxonomy, review and coverage versions are included in run provenance.

Task output includes `extraction_summary`, `validation_summary`, `review_summary`
and `coverage_summary` with candidate, decision and gap counts. An all-rejected batch fails publication with
`NoValidCandidatesError`. To retry a failed extraction with the updated prompt,
start a **new reextract run** pointing at the original source run; do not repair
the old run with a changed code/prompt configuration.

## Tests and next steps

```sh
python -m ruff check src tests
python -m pytest -q
python -m build --wheel
```

Local tests use an in-memory store to exercise orchestration; the worker image's
smoke test runs real Iceberg merges, and a deployed fixture run verifies the catalog.
Live Tavily/OpenAI research additionally requires working provider credentials.

Explicit opening aliases/ECO imports, structured-dataset collectors, engine
analysis, automatic execution of gap searches, report generation and a
run-comparison UI remain future work. The current release adds four new tables
without altering existing table schemas. No claims of comprehensive opening
coverage are made.

References: [Iceberg Spark writes](https://iceberg.apache.org/docs/latest/spark-writes/),
[OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Tavily Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract).
