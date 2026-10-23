# Deploy

Argo CD syncs `deploy/apps` (the root app-of-apps created by `infra/gitops`). Everything
in the cluster comes from here; nothing is applied by hand except one-off workflow runs.
Deployment-specific values (registry, vault, client IDs, storage names) are **cluster
facts**: annotations on Argo CD's in-cluster cluster Secret, written by
`infra/gitops/facts.tf` and read by the ApplicationSets. None of them are in this repo.

| Path | What |
|---|---|
| `apps/` | AppProjects `openings` and `platform-security`, and the Applications below |
| `catalog/` | The catalog's CloudNativePG database (one instance, Barman backups), Key Vault secrets, Lakekeeper's service account, and the catalog's network policies |
| `platform-base/` | ValidatingAdmissionPolicy: research pods run only digest-pinned `openings-*` images from the cluster registry, plus the pinned Argo executor |
| `chart/` | The research runtime: `openings-batch` and `catalog-bootstrap` WorkflowTemplates, the explorer API, provider keys, log archiving |
| `network-policies/` | Cilium default-deny ingress per namespace; ingress and egress limits for `openings-research` |

## Sync order

| Wave | Applications |
|---|---|
| 0 | `argo-workflows`, `cert-manager`, `cnpg`, `external-secrets` |
| 1 | `barman-cloud` (needs cert-manager and CNPG), `admission` |
| 2 | `catalog` (database, secrets, service account) |
| 3 | `lakekeeper` |
| 4 | `research`, which exists only after the images workflow has written `openings.yaml` to the `deploy-state` branch |
| 5 | `network-policies` |

## Rolling out new builds

Every push to `main` runs `.github/workflows/images.yml`: build both images, smoke test,
Trivy (fail on fixable criticals), push to the registry with SBOM and provenance, sign
with cosign (keyless, identity `images.yml@refs/heads/main`) and verify the signature.
The `release` job then commits both digests and the commit to `deploy-state/openings.yaml`;
the `research` ApplicationSet reads that file, so Argo CD rolls the build out. Both
images or neither: if one fails, `deploy-state` keeps the last good pair.

To roll back, `git revert` the commit on `deploy-state`. Admission in the cluster checks
that every research image is a digest from this registry, which only CI and you can push
to; signatures are verified at publish time, not again at admission.

## Entry from the internet

The only way in is an outbound Cloudflare Tunnel (`deploy/cloudflared`, routes in
`infra/gitops/edge.tf`); there is no Ingress, Gateway or LoadBalancer Service.

| Hostname | What | Access |
|---|---|---|
| `chess-openings.generops.dev` | Research explorer and read-only API | Public; the API rate-limits per client IP (`CF-Connecting-IP`) |
| `chess-openings-cd.generops.dev` | Argo CD | Cloudflare Access, Microsoft sign-in, owner only |
| `chess-openings-flows.generops.dev` | Argo Workflows | Cloudflare Access, Microsoft sign-in, owner only |

Network policies let cloudflared reach only those three Services. Port-forward still
works and needs your Entra sign-in and an authorized IP:

```powershell
kubectl port-forward -n argocd service/argocd-server 8080:443
kubectl port-forward -n argo service/argo-workflows-server 2746:2746
kubectl port-forward -n openings-research service/openings-api 8000:80
```

## First bring-up

1. Apply `infra/` (see `infra/README.md`), including `gitops`. Argo CD then syncs waves 0–3.
2. Put `catalog-encryption-key` and `tavily-api-key` in the Key Vault. The model needs no
   key: the worker calls Azure OpenAI with its workload identity.
   The catalog waits for `catalog-encryption-key` (ExternalSecret `catalog-encryption`).
3. After the first signed images build lands on `deploy-state`, `research` syncs. Then
   create the warehouse once (idempotent):

   ```powershell
   argo submit -n openings-research --from workflowtemplate/catalog-bootstrap --watch
   ```

4. Fixture run (no provider keys or paid calls), then check it in the explorer:

   ```powershell
   argo submit -n openings-research --from workflowtemplate/openings-batch --watch
   ```

## Access boundaries

- **Catalog**: Lakekeeper runs with `allowall` authorization, so the network is the
  boundary. Only pods labelled `openings.generops.dev/role: worker` or `api` in
  `openings-research` can reach it, and only Lakekeeper and the CNPG operator can reach
  the database.
- **Research namespace**: ingress only from cloudflared to the explorer API. Egress only to cluster DNS, Lakekeeper, the
  Kubernetes API and port 443 on the internet (providers, Entra ID, storage). Filtering
  by domain name would need Advanced Container Networking Services.
- **Workflow pods** run on the spot `batch` pool (Argo `workflowDefaults`), except
  `catalog-bootstrap`, which runs on the system node. Spot evictions are retried with
  the same run ID.
- **Logs**: Argo archives every step's log to the `workflow-logs` container as the
  `workflows` identity, whose only role is writing that container.
