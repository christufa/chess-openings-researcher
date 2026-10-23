# Deployment-specific facts (registry, vault, tenant, identity client IDs, storage
# names) handed to GitOps without putting them in the public repo.
#
# Argo CD reads cluster settings from Secrets labelled argocd.argoproj.io/secret-type=cluster.
# This one describes the in-cluster destination and carries the facts as annotations;
# ApplicationSets in deploy/apps select it with the cluster generator and pass the
# annotations to their charts as Helm values.
# https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Generators-Cluster/
locals {
  facts_prefix = "openings.generops.dev"
  cluster_facts = {
    "acr-login-server"          = local.compute.acr_login_server
    "key-vault-url"             = local.compute.key_vault_uri
    "tenant-id"                 = data.azurerm_client_config.current.tenant_id
    "aks-oidc-issuer"           = local.compute.aks_oidc_issuer
    "storage-account"           = local.platform.storage_account_name
    "research-container"        = local.platform.research_container
    "catalog-backups-container" = local.platform.catalog_backups_container
    "workflow-logs-container"   = local.platform.workflow_logs_container
    "catalog-client-id"         = local.compute.identity_client_ids["catalog"]
    "backup-client-id"          = local.compute.identity_client_ids["backup"]
    "workflows-client-id"       = local.compute.identity_client_ids["workflows"]
    "secrets-client-id"         = local.compute.identity_client_ids["secrets"]
  }
}

resource "kubernetes_secret_v1" "in_cluster" {
  metadata {
    name      = "in-cluster"
    namespace = kubernetes_namespace_v1.argocd.metadata[0].name
    labels = {
      "argocd.argoproj.io/secret-type" = "cluster"
      "${local.facts_prefix}/facts"    = "true"
    }
    annotations = { for k, v in local.cluster_facts : "${local.facts_prefix}/${k}" => v }
  }
  data = {
    name   = "in-cluster"
    server = "https://kubernetes.default.svc"
    config = jsonencode({ tlsClientConfig = { insecure = false } })
  }
}
