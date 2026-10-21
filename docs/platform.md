# Private platform deployment

Status: configured and locally tested, not provisioned. No DNS activation or
production research run has occurred. Keep the draft PR open and automatic sync
disabled until the acceptance checks below pass.

## Azure quota gate

On 2026-10-21, East US 2 reported 14/46 total regional vCPUs used and
0/0 Standard DDSv5-family vCPUs. Both Standard_D4ds_v5 and Standard_D8ds_v5
reported NotAvailableForSubscription in availability zones 1, 2 and 3.
Request 128 DDSv5-family vCPUs and 160 total regional vCPUs, with zonal
availability for those SKUs. These are target limits, not incremental increases.
Quota approval does not guarantee zonal capacity; verify both again before apply.

The current minimum is three D4ds_v5 system nodes plus three D8ds_v5 research
nodes: 36 vCPUs. Three research nodes are needed for the databases' required
zone anti-affinity. Current pool maxima consume 84 vCPUs before upgrade surge;
33% concurrent surge brings that to 116. The recommendation includes room for
future private runners and existing subscription workloads. No quota request
has been submitted automatically.

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

Key Vault secret names are `catalog-encryption-key` and
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
