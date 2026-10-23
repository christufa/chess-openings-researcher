output "resource_group_name" {
  value = azurerm_resource_group.platform.name
}

output "storage_account_name" {
  value = azurerm_storage_account.research.name
}

# ---- Read by ../compute and ../gitops through terraform_remote_state ----

output "location" {
  value = azurerm_resource_group.platform.location
}

output "storage_account_id" {
  value = azurerm_storage_account.research.id
}

output "research_container" {
  value = azurerm_storage_container.research.name
}

output "catalog_backups_container" {
  value = azurerm_storage_container.catalog_backups.name
}

output "workflow_logs_container" {
  value = azurerm_storage_container.workflow_logs.name
}

output "aks_subnet_id" {
  value = azurerm_subnet.aks.id
}
