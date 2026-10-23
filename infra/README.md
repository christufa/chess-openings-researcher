# Infrastructure

A lean, private Azure platform for collecting opening research: one AKS cluster
that idles at a single node, an ADLS Gen2 account for the Iceberg warehouse and
catalog backups, a Key Vault for provider keys, and a Basic registry. Nothing is
published to the internet: there is no ingress, gateway or DNS record.

| Stack | What | State |
|---|---|---|
| `bootstrap` | State account (operator IP only, versioned, locked) and the monthly budget | local, then migrated |
| `platform` | Resource group, VNet + AKS subnet (service endpoints), research storage account with `research`, `catalog-backups` and `workflow-logs` containers | `platform.tfstate` |
| `compute` | Keyless Azure OpenAI (`gpt-5.4-mini`, DataZoneStandard), AKS (Free tier, system pool 1–2, spot `batch` pool 0–1), ACR, Key Vault, workload identities, GitHub OIDC push identity | `compute.tfstate` |
| `gitops` | Argo CD, the root app-of-apps (`deploy/apps`) and the cluster facts | `gitops.tfstate` |

Node pools and quotas come from [`capacity.json`](capacity.json), which both
`compute` and the preflight read.

## What stays private

- **Data**: the storage account and Key Vault deny by default with no trusted-service
  bypass. Only the AKS subnet (service endpoint) and your IP get through. Storage
  is keyless (Entra ID and user-delegation SAS only).
- **Cluster**: Entra ID + Azure RBAC only, local accounts and run-command disabled,
  and the API server answers only your IP ranges.
- **Workloads**: Argo CD, Argo Workflows and the research explorer are reached with
  `kubectl port-forward`; none has a Service of type LoadBalancer or an ingress.
- **Identities**: one workload identity per component, scoped to its own container
  (catalog → `research`, backup → `catalog-backups`, workflows → `workflow-logs`)
  or to reading the vault. The worker and API get table-scoped credentials from
  Lakekeeper, not Azure roles. CI can only push images, only from `main`.

The registry is not private: it holds only images built from this public repository.

## Firewalls and your IP

Terraform owns the firewall design and **never sets or reads IP rules**. Add your
IP by hand; changes you make in Azure never show up as drift.

| Resource | Portal page | When |
|---|---|---|
| State account | Set by `TF_VAR_operator_ipv4` in bootstrap | Before `bootstrap` |
| Research storage (`stopenings…`) | Storage account → Networking → Firewall | Right after `platform` |
| AKS `aks-openings` | Kubernetes service → Networking → Authorized IP ranges | Right after `compute`; until then its API answers any IP (Entra sign-in still required) |
| Key Vault (`kv-openings-…`) | Key vault → Networking → Firewall | Only while you set secret values |

Signs of a stale IP: `terraform init/plan` fails reading state (403), `kubectl` times out.

## Order

Check quota first. The spot quota (`lowPriorityCores`) is shared with any other
cluster in the subscription:

```powershell
python -m pip install -e .   # once, from the repository root
python -m openings_research.azure_preflight --subscription <subscription-id>
```

Then, from `infra/`, with your `az login` session:

1. `bootstrap`: copy `terraform.tfvars.example` to `terraform.tfvars`, set
   `$env:TF_VAR_operator_ipv4`, then `terraform init`, `plan -out main.tfplan`,
   `apply main.tfplan`. Migrate its state with an ignored `backend.local.tf`
   (`terraform { backend "azurerm" {} }`) and `terraform init -migrate-state`
   using the `backend` output and `key=bootstrap.tfstate`.
2. Copy `state.tfbackend.example` to `state.tfbackend` and fill it from
   `terraform -chdir=bootstrap output backend`.
3. `platform`, then `compute`, then `gitops`, each with
   `terraform init "-backend-config=../state.tfbackend"`, a saved plan and its apply.
   `gitops` needs `kubelogin` (`az aks install-cli`); Argo CD then syncs `deploy/apps`
   (see [deploy/README.md](../deploy/README.md) for the sync order and first bring-up).
4. Put `tavily-api-key` and `catalog-encryption-key` in the Key Vault (your IP added
   first). Keep a copy of the encryption key outside Azure: without it, a restored catalog
   database cannot decrypt its stored settings. The model needs no key: the worker calls
   Azure OpenAI as its workload identity, and the account has key authentication disabled.

## GitHub secrets for the images workflow

Set these repository secrets from the `compute` outputs. They are identifiers, not
credentials, but secrets are masked in this public repository's logs:

| Secret | Value |
|---|---|
| `AZURE_CLIENT_ID` | `terraform -chdir=compute output -raw ci_client_id` |
| `AZURE_TENANT_ID` | your tenant ID |
| `ACR_LOGIN_SERVER` | `terraform -chdir=compute output -raw acr_login_server` |

The CI identity trusts `repo:<github_oidc_repository>:ref:refs/heads/main`. This repository
uses GitHub's immutable subject format (`owner@<owner-id>/<repo>@<repo-id>`), so set
`github_oidc_repository` in `compute/terraform.tfvars` to the `sub_claim_prefix` that
`gh api repos/<owner>/<repo>/actions/oidc/customization/sub` reports, without `repo:`.
The images workflow prints the subject it presents if sign-in fails.

## Recovery

- Research data: ZRS, 30-day soft delete, a delete lock and `prevent_destroy`.
- Catalog database: one CloudNativePG instance with Barman WAL archiving and
  daily base backups to `catalog-backups` (30 days).
- Key Vault: purge protection and `prevent_destroy`.

## Validate without Azure

```powershell
terraform fmt -check -recursive infra
terraform -chdir=infra/compute init -backend=false
terraform -chdir=infra/compute validate
terraform -chdir=infra/compute test
```
