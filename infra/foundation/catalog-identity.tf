# Trust only the dedicated catalog service account. Workers receive table-scoped
# credentials from Lakekeeper rather than an account-wide Azure data role.
resource "azurerm_user_assigned_identity" "catalog" {
  name                = "id-${var.name}-catalog"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  tags                = local.tags
}
resource "azurerm_federated_identity_credential" "catalog" {
  name                      = "aks-catalog"
  user_assigned_identity_id = azurerm_user_assigned_identity.catalog.id
  issuer                    = azurerm_kubernetes_cluster.main.oidc_issuer_url
  audience                  = ["api://AzureADTokenExchange"]
  subject                   = "system:serviceaccount:openings-catalog:lakekeeper"
}
# Delegation-key creation is account scoped. Blob access is granted separately
# against the research container by the private data stack.
resource "azurerm_role_assignment" "catalog_delegator" {
  scope                = azurerm_storage_account.research.id
  role_definition_name = "Storage Blob Delegator"
  principal_id         = azurerm_user_assigned_identity.catalog.principal_id
}
output "catalog_client_id" { value = azurerm_user_assigned_identity.catalog.client_id }
output "catalog_principal_id" { value = azurerm_user_assigned_identity.catalog.principal_id }
output "storage_account_id" { value = azurerm_storage_account.research.id }
