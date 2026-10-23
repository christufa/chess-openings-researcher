output "resource_group_name" {
  value = azurerm_resource_group.compute.name
}

output "aks_name" {
  value = azurerm_kubernetes_cluster.main.name
}

# az aks get-credentials --resource-group <resource_group_name> --name <aks_name>
output "aks_oidc_issuer" {
  value = azurerm_kubernetes_cluster.main.oidc_issuer_url
}

output "acr_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "key_vault_uri" {
  value = azurerm_key_vault.main.vault_uri
}

# GitHub repository variable AZURE_CI_CLIENT_ID for the images workflow.
output "ci_client_id" {
  value = azurerm_user_assigned_identity.ci.client_id
}

# ---- Read by ../gitops and written into the cluster facts ----

output "identity_client_ids" {
  value = { for name, identity in azurerm_user_assigned_identity.workload : name => identity.client_id }
}

output "capacity_requirements" {
  description = "vCPUs per quota for first deployment; check them with python -m openings_research.azure_preflight"
  value = {
    for quota in distinct([for pool in values(local.capacity.pools) : pool.quota]) : quota => {
      startup = sum([for pool in values(local.capacity.pools) : pool.min_count * pool.vcpus if pool.quota == quota])
      maximum_with_surge = sum([
        for pool in values(local.capacity.pools) :
        (pool.max_count + ceil(pool.max_count * local.capacity.surge_percent / 100)) * pool.vcpus
        if pool.quota == quota
      ])
    }
  }
}
