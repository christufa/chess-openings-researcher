locals {
  platform_principals = {
    admission            = { identity = "admission", subject = "system:serviceaccount:kyverno:openings-admission" }
    backup-catalog       = { identity = "backup", subject = "system:serviceaccount:openings-catalog:catalog-pg" }
    backup-authorization = { identity = "backup", subject = "system:serviceaccount:openings-catalog:authorization-pg" }
    catalog-secrets      = { identity = "secrets", subject = "system:serviceaccount:openings-catalog:openings-secrets" }
    research-secrets     = { identity = "secrets", subject = "system:serviceaccount:openings-research:openings-secrets" }
    query-secrets        = { identity = "secrets", subject = "system:serviceaccount:openings-query:openings-secrets" }
  }
}
resource "azurerm_user_assigned_identity" "platform" {
  for_each            = toset(["backup", "secrets", "admission"])
  name                = "id-${var.name}-${each.key}"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  tags                = local.tags
}
resource "azurerm_federated_identity_credential" "platform" {
  for_each                  = local.platform_principals
  name                      = each.key
  user_assigned_identity_id = azurerm_user_assigned_identity.platform[each.value.identity].id
  issuer                    = azurerm_kubernetes_cluster.main.oidc_issuer_url
  audience                  = ["api://AzureADTokenExchange"]
  subject                   = each.value.subject
}
resource "azurerm_role_assignment" "secret_reader" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.platform["secrets"].principal_id
}
output "backup_client_id" { value = azurerm_user_assigned_identity.platform["backup"].client_id }
output "backup_principal_id" { value = azurerm_user_assigned_identity.platform["backup"].principal_id }
output "secrets_client_id" { value = azurerm_user_assigned_identity.platform["secrets"].client_id }
resource "azurerm_role_assignment" "admission_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.platform["admission"].principal_id
}
output "admission_client_id" { value = azurerm_user_assigned_identity.platform["admission"].client_id }
