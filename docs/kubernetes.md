# Kubernetes / Iceberg deployment

This is the research pipeline's only runtime. It does not read the Lichess game
tables. All research tables live in one namespace, `openings_research`, in an
explicitly configured Iceberg warehouse. The earlier Databricks/Delta runtime has
been removed; its workspace no longer resolves and its data is not migrated.

The cluster itself is described in [infra/README.md](../infra/README.md).

## Architecture

Argo batch → one Spark worker per opening → Tavily → extraction → validation →
review → Iceberg publication → FastAPI / research explorer (pyiceberg + DuckDB).

Each worker runs the five stages in one process; API calls stay on the driver.
Each table merge is atomic, but there is no transaction spanning tables. The
`research_runs.status = completed` marker is the publication boundary. The API
checks it before serving records and selects only completed runs for the library.
It does not depend on Spark views being readable outside Spark. Failed runs remain in
history. Current results are replacement snapshots, not a union of old claims.

The Argo template serializes the entire batch with a namespace-scoped mutex.
Use a single installation/writer for this warehouse; the mutex does not protect
against unrelated clients, other namespaces, or manual jobs. Each opening has a
stable workflow UID/index run ID for retries. A new workflow creates new runs.
At most 50 distinct openings are accepted; the default is the credential-free
smoke fixture. Each opening is limited to one hour; the batch to 24 hours. This
is a workload/time bound, not a dollar cap. Review and extraction retain their
existing request/output limits. A separate research warehouse avoids accidental
writes into games namespaces.

## Cluster setup

Argo CD installs the catalog, controllers and this runtime from `deploy/apps`; see
[deploy/README.md](../deploy/README.md) for the sync order, the one-time
`catalog-bootstrap` workflow and the access boundaries. Lakekeeper authenticates the
worker with its projected `lakekeeper`-audience token and vends table-scoped storage
credentials. Provider and catalog URLs are untrusted source material, not instructions.

## Build and validate locally

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
docker build -f docker/Dockerfile.worker -t openings-worker:local .
docker run --rm --read-only --tmpfs /tmp:rw,exec,size=2g --memory 4g --cpus 2 --entrypoint /opt/spark/bin/spark-submit openings-worker:local --master 'local[2]' --driver-memory 2g /opt/research/smoke_iceberg.py
docker build -f docker/Dockerfile.api -t openings-api:local .
```

The smoke test uses a disposable Hadoop Iceberg catalog on local files, runs
all five stages and replays them, checking that counts do not grow. It tests
real Iceberg merges; it does not certify remote REST auth or ADLS access.
`exec` on the temporary filesystem allows the Parquet compression JNI library
to load. The root filesystem remains read-only and the process is non-root.

## Run

```powershell
argo submit --namespace openings-research --from workflowtemplate/openings-batch --watch
kubectl port-forward --namespace openings-research service/openings-api 8000:80
```

Open `http://localhost:8000` for the explorer and `/api/docs` for the read-only API.
The explorer pages through openings and records, shows the latest 100 runs,
shows source excerpts, and compares two completed runs for the same opening.
Comparison is exact record identity (including claim category/text), not semantic
equivalence. The API caps pages at 100 and comparisons at 999 unique records of
each kind. It never exposes raw model responses or accepts arbitrary SQL. It is public at
https://chess-openings.generops.dev through the Cloudflare Tunnel, and rate-limits `/api/`
per client IP (60-request burst, 5 per second; `OPENINGS_RATE_LIMIT_*`).

For the major-opening batch after the fixture succeeds:

```powershell
argo submit --namespace openings-research --from workflowtemplate/openings-batch -p agent=openai -p "openings=$(Get-Content batches/major-openings-20.json -Raw)"
```

To extract again from the sources a previous run already saved (no new web searches;
the model is called again), pass that run's ID. Its `research_runs.run_id` is
`<workflow uid>-<index>`:

```powershell
argo submit --namespace openings-research --from workflowtemplate/openings-batch -p agent=openai -p 'openings=["Italian Game"]' -p mode=reextract -p source-run-id=<run-id>
```

Use the Argo UI/history for failures. Infrastructure retries reuse the same run
ID; changed code/prompts require a new workflow. There is no scheduled research.
Do not garbage-collect source versions referenced by historical evidence. Iceberg
compaction and snapshot maintenance need a separately scoped operational policy.

## Serving

The API reads Iceberg directly: pyiceberg loads each table the query names from the
REST catalog (signed in with the pod's projected `lakekeeper` token, re-read when it
rotates), scans it with the SAS token Lakekeeper vends, and DuckDB runs the reader's
parameterized SQL over the Arrow data in memory. Research tables are small, so whole
tables are scanned and cached until their snapshot changes. There is no query engine
to run and no storage role on the API. Readiness means the catalog answered and the
research namespace is listable.

## Next milestones

1. Deploy a fixture and verify it through the explorer on the cluster.
2. Add ECO/alias identities, curated branch benchmarks, and gap-directed collection.
3. Add explicit request budgets, human adjudication and quality regression gates.
4. Connect aggregate games statistics through the existing read-only data API;
   opening-name matching alone is not a reliable position join.

References: [Iceberg Spark writes](https://iceberg.apache.org/docs/latest/spark-writes/),
[REST catalog](https://iceberg.apache.org/docs/latest/rest-catalog/).
