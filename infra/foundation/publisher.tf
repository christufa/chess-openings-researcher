resource "azurerm_user_assigned_identity" "publisher" {
  name                = "id-${var.name}-publisher"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  tags                = local.tags
}
resource "azurerm_federated_identity_credential" "publisher" {
  name                      = "github-production"
  user_assigned_identity_id = azurerm_user_assigned_identity.publisher.id
  issuer                    = "https://token.actions.githubusercontent.com"
  audience                  = ["api://AzureADTokenExchange"]
  subject                   = "repo:christufa/openings-researcher:environment:production"
}
resource "azurerm_role_assignment" "publish" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.publisher.principal_id
}
output "publisher_client_id" { value = azurerm_user_assigned_identity.publisher.client_id }
