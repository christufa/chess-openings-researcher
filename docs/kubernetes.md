# Kubernetes / Iceberg deployment

This is the research pipeline's only runtime. It does not read the Lichess game
tables. All research tables live in one namespace, `openings_research`, in an
explicitly configured Iceberg warehouse. The earlier Databricks/Delta runtime has
been removed; its workspace no longer resolves and its data is not migrated.

The cluster itself is described in [infra/README.md](../infra/README.md). This
document still describes Trino-based serving, which is being replaced by direct
Iceberg reads from the API.

## Architecture

Argo batch → one Spark worker per opening → Tavily → extraction → validation →
review → Iceberg publication → Trino → FastAPI / research explorer.

Each worker runs the five stages in one process; API calls stay on the driver.
Each table merge is atomic, but there is no transaction spanning tables. The
`research_runs.status = completed` marker is the publication boundary. The API
checks it before serving records and selects only completed runs for the library.
It does not depend on Spark views being portable to Trino. Failed runs remain in
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
real Iceberg merges; it does not certify remote REST auth, ADLS or Trino grants.
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
each kind. It never exposes raw model responses or accepts arbitrary SQL, and it
is never published: port-forward is the only way in.

For the major-opening batch after the fixture succeeds:

```powershell
argo submit --namespace openings-research --from workflowtemplate/openings-batch -p agent=openai -p "openings=$(Get-Content batches/major-openings-20.json -Raw)"
```

Use the Argo UI/history for failures. Infrastructure retries reuse the same run
ID; changed code/prompts require a new workflow. There is no scheduled research.
Do not garbage-collect source versions referenced by historical evidence. Iceberg
compaction and snapshot maintenance need a separately scoped operational policy.

## Next milestones

1. Serve the explorer from Iceberg directly (pyiceberg + DuckDB) instead of Trino;
   deploy a fixture and verify it through the explorer.
2. Export/import existing Delta runs with ID preservation and reconciliation,
   rather than silently starting an empty library or copying partial publications.
3. Add ECO/alias identities, curated branch benchmarks, and gap-directed collection.
4. Add explicit request budgets, human adjudication and quality regression gates.
5. Connect aggregate games statistics through the existing read-only data API;
   opening-name matching alone is not a reliable position join.

References: [Iceberg Spark writes](https://iceberg.apache.org/docs/latest/spark-writes/),
[REST catalog](https://iceberg.apache.org/docs/latest/rest-catalog/).
