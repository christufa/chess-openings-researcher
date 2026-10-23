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

## Nothing is published

No Ingress, Gateway, LoadBalancer Service or tunnel. Reach the UIs with port-forward,
which needs your Entra sign-in and an authorized IP:

```powershell
kubectl port-forward -n argocd service/argocd-server 8080:443
kubectl port-forward -n argo service/argo-workflows-server 2746:2746
kubectl port-forward -n openings-research service/openings-api 8000:80
```

## First bring-up

1. Apply `infra/` (see `infra/README.md`), including `gitops`. Argo CD then syncs waves 0–3.
2. Put `catalog-encryption-key`, `openai-api-key` and `tavily-api-key` in the Key Vault.
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
- **Research namespace**: no ingress. Egress only to cluster DNS, Lakekeeper, the
  Kubernetes API and port 443 on the internet (providers, Entra ID, storage). Filtering
  by domain name would need Advanced Container Networking Services.
- **Workflow pods** run on the spot `batch` pool (Argo `workflowDefaults`), except
  `catalog-bootstrap`, which runs on the system node. Spot evictions are retried with
  the same run ID.
- **Logs**: Argo archives every step's log to the `workflow-logs` container as the
  `workflows` identity, whose only role is writing that container.
