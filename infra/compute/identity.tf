# Workload identities: one per component, least privilege, each trusted for exactly
# one Kubernetes service account. No keys or SAS tokens anywhere. The research worker
# and API have no data role of their own: Lakekeeper vends them table-scoped credentials.
locals {
  workload_identities = {
    # Lakekeeper reads and writes table metadata and vends user-delegation SAS for the
    # research container only.
    catalog = {
      subject = "system:serviceaccount:${local.catalog_namespace}:lakekeeper"
      roles = {
        data      = { scope = "${local.container_scope}/${local.platform.research_container}", role = "Storage Blob Data Contributor" }
        delegator = { scope = local.platform.storage_account_id, role = "Storage Blob Delegator" } # account scoped by design
      }
    }
    # CloudNativePG names the service account after the cluster (catalog-pg).
    backup = {
      subject = "system:serviceaccount:${local.catalog_namespace}:catalog-pg"
      roles = {
        data = { scope = "${local.container_scope}/${local.platform.catalog_backups_container}", role = "Storage Blob Data Contributor" }
      }
    }
    # Workflow pods (openings-worker): archive step logs, and call Azure OpenAI
    # (role in openai.tf).
    workflows = {
      subject = "system:serviceaccount:${local.research_namespace}:openings-worker"
      roles = {
        data = { scope = "${local.container_scope}/${local.platform.workflow_logs_container}", role = "Storage Blob Data Contributor" }
      }
    }
  }

  # External Secrets: one namespaced SecretStore per namespace, each with its own
  # openings-secrets service account; both read the vault and nothing else.
  secrets_subjects = {
    catalog  = "system:serviceaccount:${local.catalog_namespace}:openings-secrets"
    research = "system:serviceaccount:${local.research_namespace}:openings-secrets"
  }

  workload_roles = merge([
    for name, identity in local.workload_identities : {
      for key, grant in identity.roles : "${name}-${key}" => merge(grant, { identity = name })
    }
  ]...)
}

resource "azurerm_user_assigned_identity" "workload" {
  for_each            = toset(concat(keys(local.workload_identities), ["secrets"]))
  name                = "id-${var.project}-${each.key}"
  resource_group_name = azurerm_resource_group.compute.name
  location            = azurerm_resource_group.compute.location
  tags                = local.tags
}

resource "azurerm_federated_identity_credential" "workload" {
  for_each                  = local.workload_identities
  name                      = "aks-${each.key}"
  user_assigned_identity_id = azurerm_user_assigned_identity.workload[each.key].id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = azurerm_kubernetes_cluster.main.oidc_issuer_url
  subject                   = each.value.subject
}

resource "azurerm_role_assignment" "workload" {
  for_each             = local.workload_roles
  scope                = each.value.scope
  role_definition_name = each.value.role
  principal_id         = azurerm_user_assigned_identity.workload[each.value.identity].principal_id
}

resource "azurerm_federated_identity_credential" "secrets" {
  for_each                  = local.secrets_subjects
  name                      = "aks-secrets-${each.key}"
  user_assigned_identity_id = azurerm_user_assigned_identity.workload["secrets"].id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = azurerm_kubernetes_cluster.main.oidc_issuer_url
  subject                   = each.value
}

resource "azurerm_role_assignment" "secrets_reader" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.workload["secrets"].principal_id
}
