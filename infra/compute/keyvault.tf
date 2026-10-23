# Key Vault: the only place secret values live (OpenAI and Tavily keys, the catalog
# encryption key). Kubernetes gets them through External Secrets, signed in with
# workload identity. Terraform never reads or writes secret values.
#
# Firewall: deny by default, AKS subnet allowed (service endpoint). To set secrets
# from your PC, add your IP by hand in the portal; Terraform ignores ip_rules.
resource "azurerm_key_vault" "main" {
  name                       = "kv-${var.project}-${random_string.suffix.result}"
  resource_group_name        = azurerm_resource_group.compute.name
  location                   = azurerm_resource_group.compute.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  soft_delete_retention_days = 90
  purge_protection_enabled   = true # the catalog encryption key must not be purged by mistake

  public_network_access_enabled = true # reachable only as the firewall below allows
  network_acls {
    default_action             = "Deny"
    bypass                     = "None"
    virtual_network_subnet_ids = [local.platform.aks_subnet_id]
    ip_rules                   = []
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [network_acls[0].ip_rules] # your IP is set by hand in Azure
  }
}

# You: create and update secret values (portal, or az keyvault secret set).
resource "azurerm_role_assignment" "kv_me" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}
