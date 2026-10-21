output "resource_group" { value = azurerm_resource_group.main.name }
output "cluster_name" { value = azurerm_kubernetes_cluster.main.name }
output "oidc_issuer" { value = azurerm_kubernetes_cluster.main.oidc_issuer_url }
output "registry" { value = azurerm_container_registry.main.login_server }
output "storage_account" { value = azurerm_storage_account.research.name }
output "key_vault_id" { value = azurerm_key_vault.main.id }
