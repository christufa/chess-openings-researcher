locals {
  tags = { application = "openings-researcher", environment = "production", managed_by = "terraform" }
}

resource "azurerm_resource_group" "main" {
  name     = "rg-${var.name}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_virtual_network" "main" {
  name                = "vnet-${var.name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  address_space       = ["10.84.0.0/16"]
  tags                = local.tags
}

resource "azurerm_subnet" "nodes" {
  name                 = "aks"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.84.0.0/20"]
}

resource "azurerm_subnet" "endpoints" {
  name                 = "private-endpoints"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.84.16.0/24"]
}

resource "azurerm_user_assigned_identity" "cluster" {
  name                = "id-${var.name}-cluster"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "network" {
  scope                = azurerm_subnet.nodes.id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_user_assigned_identity.cluster.principal_id
}

resource "azurerm_user_assigned_identity" "kubelet" {
  name                = "id-${var.name}-kubelet"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "kubelet_operator" {
  scope                = azurerm_user_assigned_identity.kubelet.id
  role_definition_name = "Managed Identity Operator"
  principal_id         = azurerm_user_assigned_identity.cluster.principal_id
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "logs-${var.name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_kubernetes_cluster" "main" {
  name                      = "aks-${var.name}"
  resource_group_name       = azurerm_resource_group.main.name
  location                  = var.location
  dns_prefix                = var.name
  kubernetes_version        = var.kubernetes_version
  sku_tier                  = "Standard"
  private_cluster_enabled   = true
  local_account_disabled    = true
  oidc_issuer_enabled       = true
  workload_identity_enabled = true
  azure_policy_enabled      = true
  run_command_enabled       = false
  automatic_upgrade_channel = "patch"
  node_os_upgrade_channel   = "NodeImage"
  tags                      = local.tags
  default_node_pool {
    name                         = "system"
    vm_size                      = "Standard_D4ds_v5"
    auto_scaling_enabled         = true
    min_count                    = 3
    max_count                    = 5
    zones                        = ["1", "2", "3"]
    vnet_subnet_id               = azurerm_subnet.nodes.id
    only_critical_addons_enabled = true
    temporary_name_for_rotation  = "systemtmp"
    upgrade_settings { max_surge = "33%" }
  }
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.cluster.id]
  }
  kubelet_identity {
    client_id                 = azurerm_user_assigned_identity.kubelet.client_id
    object_id                 = azurerm_user_assigned_identity.kubelet.principal_id
    user_assigned_identity_id = azurerm_user_assigned_identity.kubelet.id
  }
  azure_active_directory_role_based_access_control {
    tenant_id          = var.tenant_id
    azure_rbac_enabled = true
  }
  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium"
    network_policy      = "cilium"
    pod_cidr            = "10.85.0.0/16"
    service_cidr        = "10.86.0.0/16"
    dns_service_ip      = "10.86.0.10"
    load_balancer_sku   = "standard"
  }
  oms_agent {
    log_analytics_workspace_id      = azurerm_log_analytics_workspace.main.id
    msi_auth_for_monitoring_enabled = true
  }
  key_vault_secrets_provider { secret_rotation_enabled = true }
  depends_on = [azurerm_role_assignment.network, azurerm_role_assignment.kubelet_operator]
}

resource "azurerm_kubernetes_cluster_node_pool" "research" {
  name                  = "research"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.main.id
  vm_size               = "Standard_D8ds_v5"
  auto_scaling_enabled  = true
  min_count             = 2
  max_count             = 8
  zones                 = ["1", "2", "3"]
  vnet_subnet_id        = azurerm_subnet.nodes.id
  upgrade_settings { max_surge = "33%" }
  tags = local.tags
}

resource "azurerm_role_assignment" "operator" {
  scope                = azurerm_kubernetes_cluster.main.id
  role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"
  principal_id         = var.operator_object_id
}

resource "azurerm_container_registry" "main" {
  name                          = "openings${var.resource_suffix}"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = var.location
  sku                           = "Premium"
  admin_enabled                 = false
  public_network_access_enabled = false
  tags                          = local.tags
}

resource "azurerm_role_assignment" "pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.kubelet.principal_id
}

resource "azurerm_storage_account" "research" {
  name                            = "openings${var.resource_suffix}"
  resource_group_name             = azurerm_resource_group.main.name
  location                        = var.location
  account_tier                    = "Standard"
  account_replication_type        = "ZRS"
  is_hns_enabled                  = true
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  public_network_access_enabled   = false
  allow_nested_items_to_be_public = false
  blob_properties {
    delete_retention_policy { days = 30 }
    container_delete_retention_policy { days = 30 }
  }
  tags = local.tags
  lifecycle { prevent_destroy = true }
}

resource "azurerm_key_vault" "main" {
  name                          = "kv-openings-${var.resource_suffix}"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = var.location
  tenant_id                     = var.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  purge_protection_enabled      = true
  soft_delete_retention_days    = 90
  public_network_access_enabled = false
  tags                          = local.tags
  lifecycle { prevent_destroy = true }
}

locals {
  endpoints = {
    blob  = { zone = "privatelink.blob.core.windows.net", target = azurerm_storage_account.research.id, group = "blob" }
    dfs   = { zone = "privatelink.dfs.core.windows.net", target = azurerm_storage_account.research.id, group = "dfs" }
    vault = { zone = "privatelink.vaultcore.azure.net", target = azurerm_key_vault.main.id, group = "vault" }
    acr   = { zone = "privatelink.azurecr.io", target = azurerm_container_registry.main.id, group = "registry" }
  }
}
resource "azurerm_private_dns_zone" "main" {
  for_each            = local.endpoints
  name                = each.value.zone
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}
resource "azurerm_private_dns_zone_virtual_network_link" "main" {
  for_each              = local.endpoints
  name                  = "openings"
  resource_group_name   = azurerm_resource_group.main.name
  private_dns_zone_name = azurerm_private_dns_zone.main[each.key].name
  virtual_network_id    = azurerm_virtual_network.main.id
}
resource "azurerm_private_endpoint" "main" {
  for_each            = local.endpoints
  name                = "pe-${var.name}-${each.key}"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  subnet_id           = azurerm_subnet.endpoints.id
  tags                = local.tags
  private_service_connection {
    name                           = each.key
    private_connection_resource_id = each.value.target
    subresource_names              = [each.value.group]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.main[each.key].id]
  }
}
