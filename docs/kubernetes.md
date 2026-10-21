# Kubernetes / Iceberg deployment

This is an additional runtime for the existing research pipeline. It does not
migrate, delete, or read the Databricks data or the Lichess game tables. The
Databricks bundle remains supported. All research tables live in one namespace,
`openings_research`, in an explicitly configured Iceberg warehouse.

Databricks deployment is opt-in via the workflow's `deploy_databricks` input.
The old workspace hostname failed DNS resolution on October 21, 2026; this
change does not restore it or assert that its existing data is accessible.

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

## Prerequisites and isolation

- Argo Workflows supporting `synchronization.mutexes`, and Helm 3.
- An Iceberg REST catalog/warehouse for research, with an ADLS storage location.
- An explicitly provisioned catalog principal for the `openings-worker` service
  account, scoped to this warehouse. Set the catalog token audience to match the
  catalog's configuration; the example value is not proof of a trust relationship.
- A Trino Iceberg catalog pointing at that same research warehouse. Grant the
  `openings-api` principal SELECT only on the research namespace. It needs no
  games permissions and no provider keys. The projected token is re-read for
  every connection; worker catalog tokens last two hours and workers at most one.
- Catalog and Trino network policies must explicitly allow the new namespace.
  Those permissions are external prerequisites, not edits applied by this chart.
- A CA ConfigMap containing `ca.crt` for Trino HTTPS. Catalog HTTPS must be trusted
  by the worker JVM; configure its trust store if using a private CA.
- A Secret `openings-provider-keys` with `OPENAI_API_KEY` and `TAVILY_API_KEY` for
  real research, preferably managed by External Secrets. Fixture runs need neither.

The chart uses existing infrastructure and creates no cluster-wide resources or
public routes. Install in a dedicated `openings-research` namespace. It denies
pod ingress by default; egress must be constrained according to the site's
catalog/storage/provider endpoints before exposing this service. Provider and
catalog URLs are untrusted source material, not executable instructions.

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

## Install after infrastructure permissions are provisioned

Build/publish images to your registry and use immutable digests. CI currently
builds and tests images but does not publish them or alter a cluster. Image
signing/admission must follow the target cluster's policy before deployment.

Create a local values file with `workerImage`, `apiImage`, `catalogUri`,
`warehouse`, `catalogTokenAudience`, `trinoHost`, `trinoCatalog`, `trinoUser`,
`trinoTokenAudience` and `caConfigMap`. Values must describe the new research
principals/catalog, with credentials scoped specifically to this application.

```powershell
helm lint deploy/chart -f research-values.yaml
helm upgrade --install openings-research deploy/chart --namespace openings-research --create-namespace -f research-values.yaml
argo submit --namespace openings-research --from workflowtemplate/openings-batch --watch
kubectl port-forward --namespace openings-research service/openings-api 8000:80
```

Open `http://localhost:8000` for the explorer and `/api/docs` for the read-only API.
The explorer pages through openings and records, shows the latest 100 runs,
shows source excerpts, and compares two completed runs for the same opening.
Comparison is exact record identity (including claim category/text), not semantic
equivalence. The API caps pages at 100 and comparisons at 999 unique records of
each kind. It never exposes raw model responses or accepts arbitrary SQL.
The API has no end-user authentication or rate limiter yet; keep it internal
or behind an authenticated gateway. Its readiness probe checks Trino connectivity,
not all table grants; the fixture workflow and API queries validate those.

For the major-opening batch after the fixture succeeds:

```powershell
argo submit --namespace openings-research --from workflowtemplate/openings-batch -p agent=openai -p "openings=$(Get-Content batches/major-openings-20.json -Raw)"
```

Use the Argo UI/history for failures. Infrastructure retries reuse the same run
ID; changed code/prompts require a new workflow. There is no scheduled research.
Do not garbage-collect source versions referenced by historical evidence. Iceberg
compaction and snapshot maintenance need a separately scoped operational policy.

## Next milestones

1. Provision research-only warehouse grants, Trino catalog, identity trust and
   network access; deploy a fixture and verify it through Trino.
2. Export/import existing Delta runs with ID preservation and reconciliation,
   rather than silently starting an empty library or copying partial publications.
3. Add ECO/alias identities, curated branch benchmarks, and gap-directed collection.
4. Add explicit request budgets, human adjudication and quality regression gates.
5. Connect aggregate games statistics through the existing read-only data API;
   opening-name matching alone is not a reliable position join.

References: [Iceberg Spark writes](https://iceberg.apache.org/docs/latest/spark-writes/),
[REST catalog](https://iceberg.apache.org/docs/latest/rest-catalog/).
