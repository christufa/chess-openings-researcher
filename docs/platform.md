# Private platform deployment

Status: configured and locally tested, not provisioned. No DNS activation or
production research run has occurred. Keep the draft PR open and automatic sync
disabled until the acceptance checks below pass.

## Azure quota gate

The approved East US 2 quota is now **28 Ddsv6-family vCPUs** and **64 total
regional vCPUs**. The latest check observed 0 family vCPUs and 14 regional vCPUs
already used. Standard_D4ds_v6 remains advertised but restricted as
NotAvailableForSubscription in zones 1, 2 and 3. Recheck after approval propagates;
if the restriction persists, request availability for that SKU and those zones.
No additional vCPU quota is required for the reduced configuration below.

The shared `infra/foundation/capacity.json` drives Terraform and the read-only
preflight command. It now caps system nodes at two D4ds_v6 instances and research
nodes at three D4ds_v6 instances: **20 vCPUs**. Both pools have equal minimum and
maximum counts, so no workload-driven node growth is available. Concurrent 33%
upgrade surge rounds to one extra node per pool, bringing the total to **28**.
With 14 existing regional vCPUs, the combined surge requirement is 42, below 64.

This replaces the initial, larger 36–116 vCPU plan. The smaller configuration
accepts reduced system-node redundancy and workload throughput. The research
pool retains three nodes for database zone separation, with 16 GiB physical RAM
per node before AKS reservations. Resource requests and topology must be checked
against actual allocatable capacity after bootstrap; this is not a production
load-test result. Keep research batches serialized and do not add a dedicated
runner node pool within the current quota without revisiting this capacity plan.
The 28-vCPU ceiling has no spare family headroom during simultaneous upgrades.

Run from the repository root after `az login`:

```powershell
python -m openings_research.azure_preflight --subscription <subscription-uuid> --region eastus2
```

The command reads Azure usage and SKU metadata only. It reports separate startup
and full-capacity readiness, catches missing metadata and subscription/zone
restrictions, and exits 2 until full capacity is available (0 when ready).
It checks the additional requirements of **first deployment**, not incremental
headroom for an already running cluster. It is not a reservation or a complete
AKS deployment check: actual capacity, supported Kubernetes versions and other
resource quotas still need plan/apply validation. Terraform also exposes these
calculated requirements as `capacity_requirements`.

## Installation order and ownership

1. Bootstrap state, then apply foundation from reviewed main. Establish the
   private operator network path before accessing the cluster or data endpoints.
2. Apply warehouse using the catalog and backup principal outputs. Research
   data and database backups use separate containers and identities.
3. Initialize `infra/controllers` with its own remote-state key. Supply the
   foundation's cluster/resource-group names, registry hostname and admission
   identity client ID, plus subscription/tenant. The operator needs kubelogin,
   Azure CLI and authorized access to the private AKS endpoint.
4. The controllers stack installs pinned Argo CD, Argo Workflows, cert-manager,
   CloudNativePG, Barman, External Secrets, trust-manager and Kyverno charts. It
   creates restricted workload namespaces, internal CA trust and image policies,
   then the GitOps projects/root application. Terraform owns this platform layer.
   Argo CD's default project denies access; its local admin and anonymous access
   are disabled. Initially use `argocd --core` with the authorized Entra AKS
   identity. Neither Argo UI is exposed publicly.
5. Populate the dedicated Key Vault privately, then prepare immutable main-revision
   Argo Applications for `deploy/catalog` in `openings-catalog` and `deploy/query`
   in `openings-query`, both in `openings-data`. The release generator now creates
   all three applications with `--platform-values`; real main images and applied
   Azure identifiers are still needed. Review through the production root
   directory, then manually sync catalog, initialize grants, query and research
   in that order. A single reviewed release is not an atomic cluster rollout.
6. Initialize the Lakekeeper warehouse and OpenFGA grants through the dedicated
   `catalog-bootstrap` service account. Initial server/project/warehouse creation
   remains operator work. The grant reconciliation command below plans and applies
   warehouse permissions; neither runtime principal belongs to instance admins.
   Verify both allowed and denied operations before publishing a research release.

The catalog chart requires `catalogClientId`, `backup.clientId`,
`backup.destination` (the HTTPS Blob container URL), and `secrets.clientId`,
`secrets.tenantId`, `secrets.vaultUrl`. The query chart requires the secrets values,
`aksIssuer` (including its trailing slash), and a signed `bridgeImage` API digest.
The issuer comes from the actual AKS output. Keep the default internal catalog
origin unless deliberately changing service topology.

Catalog/query Key Vault secret names are `catalog-encryption-key` and
`trino-shared-secret-key`. Generate strong random values privately. External
Secrets materializes each as a `password` key; CreatedOnce avoids an unexpected
live key change. Rotation requires a coordinated maintenance procedure. Preserve
the catalog encryption key independently of PostgreSQL backups or encrypted
catalog credentials will be unrecoverable. PostgreSQL generates its own application
credentials. The ESO identity currently reads the dedicated vault; secret-level
identity separation remains a possible hardening improvement.

## Data and authentication boundaries

Lakekeeper uses Kubernetes audience-bound authentication and OpenFGA. Two
separate three-replica PostgreSQL clusters store catalog metadata and authorization
state. Barman archives WAL and schedules daily backups with 30-day retention;
this is configuration, not proof of recoverability. The database image currently
uses a version tag and must be updated, scanned and pinned before activation.

Lakekeeper serves HTTPS through a local TLS proxy. Trino accepts HTTPS JWTs only
from the research API service account with the `trino` audience. Its access rules
permit SELECT in research.openings_research and deny impersonation. A loopback
bridge re-reads the projected Lakekeeper token for each request and forwards over
verified HTTPS; it cannot access management routes or follow redirects. Catalog
read-only grants are still required: the bridge itself is not an authorization
service. Trino relies on Lakekeeper-vended storage credentials.

Trino currently has one coordinator and restarts interrupt queries. Do not claim
query-service high availability. Network policies restrict ingress; default-deny
egress with explicit dependencies is still pending. The internal root CA needs
a tested rotation/recovery procedure before its renewal window.

The image policy requires the exact main publisher identity and SHA256 image
references in research/query namespaces, including init and ephemeral containers.
It uses [Kyverno image validation](https://kyverno.io/docs/policy-types/image-validating-policy/)
with an Azure workload identity for private registry reads. Actual private-ACR
signature verification and rejection tests remain deployment gates. RoleBinding
admission constraints also remain required before automatic synchronization.

## Validation and activation gates

Local checks: Python tests and lint, Terraform validation/mock security tests,
Helm rendering of dependent charts, and a real Trino 484 TLS/JWT container test.
`tests/integration_platform.py` verifies missing credentials, wrong audience,
wrong namespace, impersonation rejection and an authorized query. CI runs it
without Azure/provider credentials. It does not exercise ADLS or Lakekeeper.

Before activation, prove all of the following in the private cluster:

- Fixture write through Spark/Lakekeeper to ADLS and read through Trino/API;
  deny writes by Trino, cross-namespace identities and unauthorized catalog admin.
- Expired-token rejection, projected-token renewal and certificate rotation.
- Denial of unsigned, wrong-signer and tagged application images, including init
  and ephemeral containers; verify a correctly signed release is admitted.
- Restore both databases and the encryption key into an isolated recovery setup,
  then read the restored Iceberg tables. Record measured recovery time/data loss.
- Ephemeral main-only publisher runners, credential rotation, egress restrictions,
  RoleBinding constraints and operational alerts.
- Public gateway limits, strict origin TLS and explicit Entra authorization for
  private administration, followed by rollback and cancellation tests.

The public DNS record and paid 20-opening run remain disabled until these gates
are met. Runner provisioning requires a dedicated GitHub App registration and
private credentials; do not store those credentials in source or use a personal
CLI token as a persistent controller credential.

## Coordinated release inputs

Use `--platform-values <platform.json>` alongside the existing release arguments.
This file accepts exactly `catalogClientId`, `backupClientId`, `secretsClientId`,
`tenantId`, `storageAccount`, `vaultName` and `aksIssuer`. Supply actual foundation
outputs, not example UUIDs. These are nonsecret identifiers. Backup container and
vault URLs are derived from names; arbitrary Helm overrides and credentials are
rejected. The query bridge uses the same signed API image as the research API.

Runtime values must use the matching service addresses:

```json
{
  "catalogUri": "https://catalog-tls.openings-catalog.svc.cluster.local:8443/catalog",
  "trinoHost": "trino.openings-query.svc.cluster.local"
}
```

All generated Applications use the same immutable main revision and manual sync.
The generator refuses to drop existing data applications during a research-only
promotion, or overwrite a customized Kustomization. Inspect the diff, including
all three resources, before opening the promotion PR.

## Warehouse grant reconciliation

After initial bootstrap/warehouse creation, run the following from the private
operator context with a short-lived `lakekeeper`-audience token file belonging to
an authorized catalog bootstrap principal and the internal CA file:

```text
python -m openings_research.catalog_access --origin https://catalog-tls.openings-catalog.svc.cluster.local:8443 --warehouse-id <warehouse-uuid> --token-file <projected-token-path> --ca-file <ca-path>
```

The default performs GETs only and prints the proposed changes. Repeat with
`--apply` to enable managed access, reconcile the direct assignments and verify
readback. It uses the management/permissions API from Lakekeeper 0.13.3; see the
[pinned API source](https://github.com/lakekeeper/lakekeeper/blob/v0.13.3/crates/authz-openfga/src/api.rs).

Only these two runtime identities are reconciled:

- `kubernetes~system:serviceaccount:openings-research:openings-worker`: create, modify.
- `kubernetes~system:serviceaccount:openings-query:trino`: select.

Managed access prevents object ownership from letting workers delegate grants.
Existing operator/other-user grants are preserved. The command removes excess
direct warehouse grants for the two managed identities; it does not audit or
remove inherited project grants, role memberships, or existing child-object
grants. Those can widen effective access and must be inspected and tested before
activation. Do not run concurrent permission reconcilers. A failed verification
leaves the observed state for inspection; it never attempts broad rollback or
recreates the warehouse. Re-running a converged configuration does not write.

The instance-admin configuration alone does not authorize permission-management
requests. Initial bootstrap must also establish the operator's OpenFGA rights.
No credentials or token contents belong in Git, command arguments or reports.
HTTPS verification is required, redirects are denied, and the token file is read
again for each request. Unit tests exercise reconciliation and failure handling;
live authorization and inherited-grant denial tests remain deployment gates.

## Research provider credentials

Coordinated releases now enable an External Secrets store in openings-research
using the existing federated secrets identity. Put provider values in the private
vault under `openai-api-key` and `tavily-api-key`; the generated Kubernetes Secret
uses `OPENAI_API_KEY` and `TAVILY_API_KEY`. Only research workers receive that
Secret. The public API has no provider-secret mount or environment reference.
No token values are rendered into Helm values or release manifests.

Provider secrets refresh hourly. New worker pods receive updated values; existing
process environments do not change. Confirm ExternalSecret Ready before a paid
run. Fixture mode can still run without provider keys, and standalone chart
rendering leaves this integration disabled unless explicitly enabled. The
namespace SecretStore and ExternalSecret are permitted by the research AppProject.
