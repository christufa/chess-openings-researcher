output "resource_group" { value = azurerm_resource_group.main.name }
output "cluster_name" { value = azurerm_kubernetes_cluster.main.name }
output "oidc_issuer" { value = azurerm_kubernetes_cluster.main.oidc_issuer_url }
output "registry" { value = azurerm_container_registry.main.login_server }
output "storage_account" { value = azurerm_storage_account.research.name }
output "key_vault_id" { value = azurerm_key_vault.main.id }

output "capacity_requirements" {
  description = "Additional vCPUs for first deployment; excludes existing subscription usage and future runner pools."
  value = {
    family  = local.capacity.family
    startup = sum([for pool in values(local.capacity.pools) : pool.min_count * pool.vcpus])
    maximum = sum([for pool in values(local.capacity.pools) : pool.max_count * pool.vcpus])
    maximum_with_surge = sum([
      for pool in values(local.capacity.pools) :
      (pool.max_count + ceil(pool.max_count * local.capacity.surge_percent / 100)) * pool.vcpus
    ])
  }
}
