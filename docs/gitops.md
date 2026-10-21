# Production release workflow

Application releases have two review boundaries: source code merges to main,
then the immutable release manifest merges to main. Publishing an image does not
deploy it. PR CI has no cloud credentials and runs on GitHub-hosted machines.

## Bootstrap state and infrastructure

The first operator runs `infra/bootstrap` with the example identifiers and an
explicit public IPv4 through `TF_VAR_operator_ipv4`. Review a saved plan before
applying it. This creates only a dedicated ZRS state account, private container,
operator role and deletion lock. Shared keys and public blob access are disabled;
the firewall permits that operator IP only. State versions and deleted blobs are
retained for 30 days. Protect the initial local state as a recovery artifact.

Bootstrap starts with local state because its backend does not exist yet. To
migrate it, create an ignored `backend.local.tf` containing
`terraform { backend "azurerm" {} }`, then run `terraform init -migrate-state`
with the backend output values and `key=bootstrap.tfstate`. Verify `terraform
state list` against the remote backend before archiving the local recovery copy.
Do not overwrite a nonempty remote state or commit local state. Keep the ignored
backend declaration for subsequent bootstrap operations.

Initialize `foundation`, `warehouse`, `controllers` and `dns` with the same backend settings and
distinct keys (`foundation.tfstate`, `warehouse.tfstate`, `controllers.tfstate`, `dns.tfstate`). Apply the
foundation from reviewed main. Its state private endpoint gives future private
runners network access without opening the public state firewall to CI ranges.
The data stack creates the private research container and grants catalog access
only to that container. Run it from the private network with an explicitly
authorized operator; foundation intentionally does not grant CI infrastructure
administrator access. Cloudflare token injection must map the GitHub secret to
`CLOUDFLARE_API_TOKEN`, and `vars.TF_VAR_ZONE_ID` to the case-sensitive Terraform
environment variable `TF_VAR_zone_id`.

Role assignment propagation may temporarily delay initial data-plane access.
Retry a failed bootstrap only after inspecting state; do not delete or recreate
the state account to fix a transient permission failure.

## Private image publication

Register disposable Linux runners with label `openings-production` inside the
new VNet. Each runner must execute a single job and then be destroyed. Provide
Docker/buildx, Azure CLI, Git, jq and outbound access to the required GitHub,
registry, vulnerability database and Sigstore endpoints. No PR workflow may use
these runners. Do not register a persistent workstation with this label.

Set these production environment variables from the applied foundation outputs:

| Variable | Value |
| --- | --- |
| `AZURE_PUBLISHER_CLIENT_ID` | `publisher_client_id` output |
| `AZURE_TENANT_ID` | Configured tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Configured subscription ID |
| `ACR_LOGIN_SERVER` | `registry` output |

Run **Publish verified production images** manually on main and approve its
production environment gate. The federated identity has AcrPush only on the new
registry. Both images are built with provenance and SBOM attestations. HIGH or
CRITICAL vulnerability findings fail publication before signing. An unsigned
candidate may remain in the private registry after a failed scan; it must never
be promoted. No blanket vulnerability ignore list is configured.

Successful jobs sign image digests with GitHub OIDC, verify the exact main workflow
identity and upload `release-api` and `release-worker` artifacts. Both artifacts
must reference the same source commit. The workflow cannot push Git commits,
change DNS, or access the Kubernetes control plane through its Azure identity.

## Git-recorded promotion

Download both successful release artifacts. Prepare a nonsecret JSON settings
file containing the real catalog HTTPS URI, Trino host and the runtime settings
documented in `docs/kubernetes.md`. Then, on a promotion branch, run:

```powershell
python -m openings_research.release --revision <full-main-commit-sha> --api-image <registry>/openings-api@sha256:<digest> --worker-image <registry>/openings-worker@sha256:<digest> --values <nonsecret-settings.json> --platform-values <nonsecret-platform.json>
```

The command fetches origin/main, requires the revision to be in its history,
rejects tags, credentials in catalog URLs and unexpected settings, and writes coordinated
research/catalog/query Applications containing the source revision and image digests. Review those files
in a PR to main. The generator validates structure and ancestry; it does not
replace signature verification or prove that the images came from that commit.
Verify publication artifacts and admission policy before sync.

Rollback uses the same PR process to restore a known-good manifest. Do not mutate
image tags or run an unrecorded imperative application rollback. Application
rollback does not roll back Iceberg data or schema; check compatibility first.

## Reconciliation boundaries

`deploy/gitops` bootstraps three AppProjects and the production root Application
after Argo CD is installed. The root reads only `deploy/environments/production`
on main. The research project permits this repository and research namespace,
with no cluster-scoped resources. Platform controllers, namespaces, secrets,
databases, identity policies and admission rules are installed separately by the
platform administrator. The root can create Applications in argocd, which is a
privileged capability: main workflow/release changes require careful review,
and the Argo default project must be locked down during controller bootstrap.

The production directory is deliberately empty until a real signed release
exists. Neither root nor child enables automatic sync yet. Enabling root
automation does not enable child automation. Before activating either, verify
the data platform, principal grants, restricted pod security, RoleBinding
boundaries and signature admission using negative tests as well as successful
fixture reads. The current chart allows Role/RoleBinding resources; admission
must prevent binding research principals to broader platform roles.

The controller Terraform stack and catalog/query charts now describe the private
platform, including backup configuration and admission rules. Follow
[the platform runbook](platform.md). Ephemeral runner provisioning, initial catalog
creation, effective-grant checks and live recovery and
admission tests remain required. The committed manifests alone do not establish
those controls or expose a public endpoint.
