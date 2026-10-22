# Production foundation

Production targets East US 2, a dedicated AKS cluster and
`openings.generops.dev`. Public users browse published research. Initial private
access belongs to the configured Entra user; never authorize every tenant user
by default. Research keys and cloud administration are not browser capabilities.

## Repository controls

The live main ruleset requires PRs, resolved conversations, and successful
`Tests and wheel` and `containers` checks from GitHub Actions against an up-to-date
branch. No bypass actors exist. Squash merging is the only enabled merge method.
Independent approval is intentionally zero for the solo maintainer. Add a trusted
maintainer before enabling independent approval requirements.

Actions use read-only default tokens, cannot approve PRs, restrict third-party
actions to `.github/policies/actions-allowlist.json`, require SHA-pinned
actions and require approval for all external contributors. Dependabot security
updates, secret scanning, push protection and private vulnerability reporting are enabled.
CodeQL scans Python and JavaScript; dependency review rejects new high/critical
vulnerabilities. Dependabot proposes weekly package, Docker, Terraform and Actions
updates. CODEOWNERS routes review requests without requiring independent approval
for the solo maintainer. See SECURITY.md for private reporting. Review workflow changes carefully before
approving any external workflow. PR jobs must never use production runners or
credentials. Do not use `pull_request_target` to execute contributed code.

The production environment permits only the main branch, requires the owner's
manual approval and disables administrator bypass. Self-review is permitted for
this solo-maintainer deployment gate. Policy request bodies live in
`.github/policies`; these files document the live configuration but are not an
automatic drift reconciler. Reconcile updates through the GitHub API and verify
the result. Do not create duplicate rulesets when updating the existing one.

## Terraform stacks

See [the GitOps runbook](gitops.md) for bootstrap-state migration, private image
publication, release preparation and activation prerequisites. `infra/bootstrap`
now defines the state backend; it has not been applied.

`infra/foundation` owns the new Azure resource group, VNet, private AKS control
plane, system/research pools, private ACR, ADLS, Key Vault, private DNS/endpoints,
monitoring and cluster operator role. It does not create database credentials,
publish secrets or deploy application workloads. Storage and vault destruction
are guarded. The checked-in example values contain identifiers, not secrets.
It also defines a production-environment federated publisher identity with
registry-only AcrPush, a separate catalog workload identity and a private state
endpoint. `infra/warehouse` creates the research container and its catalog grant from
the private network.

`infra/dns` owns only the openings A record. Supply `CLOUDFLARE_API_TOKEN` privately
with Zone DNS Edit scoped to the generops.dev zone. Supply its zone ID and the
actual gateway public IPv4 address. Use Full (strict) TLS in Cloudflare and a
valid origin certificate before enabling public traffic. This stack does not
change zone-wide TLS settings or unrelated records. If the record already exists,
import it first rather than overwrite it blindly.

All stacks require separate keys in a dedicated Azure Blob remote-state backend,
Entra authentication, blob lease locking and restricted state access. Bootstrap
that backend before `terraform init`; do not commit state or plan artifacts.
Example backend arguments are `resource_group_name`, `storage_account_name`,
`container_name`, `key`, and `use_azuread_auth=true`. No backend account has been
provisioned by this change.

For local validation, run `terraform init -backend=false` and `terraform validate`
in each stack. For deployment initialize the real backend, generate a saved plan,
review that plan and apply that exact plan. Do not use `-target` to bypass missing
dependencies. Azure name availability, quota and regional SKU support require a
real plan/apply validation; static validation does not establish deployability.

## Required deployment work

The foundation is not a complete live deployment. Before production activation:

1. Bootstrap remote state and a private network execution path for operators and
   ephemeral trusted-main deployment runners. Public PRs remain on GitHub-hosted
   runners. Never reuse a privileged persistent runner for untrusted code.
2. Provision workload identities and narrow warehouse/container grants, dedicated
   PostgreSQL with backup/restore, Lakekeeper authorization and Trino read-only
   grants. The API principal must not write tables; the worker must not administer
   infrastructure. Test real REST catalog/ADLS/Trino interoperability.
3. Install Argo CD and Argo Workflows with private Entra-protected administration.
   Restrict the application AppProject to this repo, namespace and resource kinds.
4. Provision the private runners and configure the committed publishing workflow
   to publish scanned, signed images and provenance from trusted main only. Promote
   image digests and an immutable chart/source revision through a PR; Argo CD
   reconciles that reviewed revision. No CI `kubectl apply` or direct protected-main
   push. The GitOps bootstrap chart and release generator are committed. Enforce
   signatures and digests at admission before enabling auto-sync.
5. Add the public TLS gateway, request limits and origin restrictions. Keep
   research/admin APIs private and authorize the explicit Entra principal. Install
   default-deny egress with deliberate DNS/provider/catalog/storage allowances.
6. Store provider tokens in the private secret store and establish rotation and
   audit logging. The Cloudflare DNS token has been verified and stored in the
   protected GitHub production environment along with its zone ID.
7. Exercise fixture publication, API reads, cancellation, recovery, backup restore
   and rollback before the paid 20-opening collection pass and DNS activation.

The application remains an internal validation runtime. Controller installation,
internal TLS, image admission, database backups and query authentication now have
configuration in source; none has been applied to Azure. See
[the private platform runbook](platform.md) for installation order, secret names,
quota blockers and the acceptance tests still required. Private runners, catalog
initialization/grants and the public gateway remain implementation work.

Private runner App registration is documented in [the runner setup guide](private-runners.md).
