# One on-demand system node for the always-on services (Argo CD, Argo Workflows,
# Lakekeeper and its database, External Secrets, the API). infra/capacity.json caps it at
# one node until the D*as_v5 family quota is raised (it is shared with lichess-delta-kube);
# then set the system pool's max_count back to 2 so it can grow when requests need it. Research runs on a spot pool that scales from zero, one
# serialized batch at a time. Idle cost is one node, its disk and the load balancer.
#
# Nothing is published: no ingress, gateway or DNS record. The API server is public
# but answers only Entra-authenticated callers from the IP ranges you set by hand
# in Azure (infra/README.md); the explorer is reached with kubectl port-forward.
resource "azurerm_user_assigned_identity" "aks" {
  name                = "id-${var.project}-aks"
  resource_group_name = azurerm_resource_group.compute.name
  location            = azurerm_resource_group.compute.location
  tags                = local.tags
}

# User-assigned, so it can be given rights on the subnet before the cluster exists.
resource "azurerm_role_assignment" "aks_network" {
  scope                = local.platform.aks_subnet_id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_user_assigned_identity.aks.principal_id
}

# The nodes' identity (image pulls). User-assigned too, so AcrPull can be granted
# without waiting for the cluster to create one.
resource "azurerm_user_assigned_identity" "kubelet" {
  name                = "id-${var.project}-kubelet"
  resource_group_name = azurerm_resource_group.compute.name
  location            = azurerm_resource_group.compute.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "kubelet_operator" {
  scope                = azurerm_user_assigned_identity.kubelet.id
  role_definition_name = "Managed Identity Operator"
  principal_id         = azurerm_user_assigned_identity.aks.principal_id
}

resource "azurerm_kubernetes_cluster" "main" {
  name                = "aks-${var.project}"
  resource_group_name = azurerm_resource_group.compute.name
  location            = azurerm_resource_group.compute.location
  dns_prefix          = "aks-${var.project}"
  node_resource_group = "rg-${var.project}-compute-nodes" # AKS creates and owns this one
  kubernetes_version  = var.kubernetes_version
  sku_tier            = "Free" # no uptime SLA; the control plane is free

  automatic_upgrade_channel = "patch"
  node_os_upgrade_channel   = "NodeImage"

  # Workload identity: pods exchange Kubernetes tokens for Azure tokens (identity.tf).
  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  # kubectl through Entra ID and Azure RBAC only.
  local_account_disabled            = true
  role_based_access_control_enabled = true
  run_command_enabled               = false
  azure_active_directory_role_based_access_control {
    tenant_id          = data.azurerm_client_config.current.tenant_id
    azure_rbac_enabled = true
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.aks.id]
  }

  kubelet_identity {
    client_id                 = azurerm_user_assigned_identity.kubelet.client_id
    object_id                 = azurerm_user_assigned_identity.kubelet.principal_id
    user_assigned_identity_id = azurerm_user_assigned_identity.kubelet.id
  }

  default_node_pool {
    name                         = "system"
    vm_size                      = local.capacity.pools.system.vm_size
    auto_scaling_enabled         = true
    min_count                    = local.capacity.pools.system.min_count
    max_count                    = local.capacity.pools.system.max_count
    node_count                   = local.capacity.pools.system.min_count
    only_critical_addons_enabled = false # also hosts the always-on services
    os_disk_size_gb              = 64
    vnet_subnet_id               = local.platform.aks_subnet_id
    temporary_name_for_rotation  = "systemtmp"

    upgrade_settings {
      max_surge = "${local.capacity.surge_percent}%"
    }
  }

  # Azure CNI Overlay + Cilium (network policies). None of these ranges may overlap
  # the VNet (10.84.0.0/16).
  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium"
    network_policy      = "cilium"
    pod_cidr            = "10.244.0.0/16"
    service_cidr        = "10.0.0.0/16"
    dns_service_ip      = "10.0.0.10"
    load_balancer_sku   = "standard"
    outbound_type       = "loadBalancer"
  }

  # Remove idle nodes quickly; the system pool never goes below one.
  auto_scaler_profile {
    expander                   = "least-waste"
    scale_down_unneeded        = "5m"
    scale_down_delay_after_add = "5m"
  }

  tags = local.tags

  lifecycle {
    ignore_changes = [
      api_server_access_profile,       # authorized IP ranges are set by hand in Azure
      default_node_pool[0].node_count, # the autoscaler owns this
    ]
  }

  depends_on = [azurerm_role_assignment.aks_network, azurerm_role_assignment.kubelet_operator]
}

# Spot pool for research workers: evictable at any time, which the pipeline tolerates
# (stages are idempotent, provider responses are cached, and a retry reuses the run
# ID). Pods need a toleration for the spot taint and nodeSelector workload=batch.
resource "azurerm_kubernetes_cluster_node_pool" "batch" {
  name                  = "batch"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.main.id
  vm_size               = local.capacity.pools.batch.vm_size
  vnet_subnet_id        = local.platform.aks_subnet_id
  os_disk_size_gb       = 64

  priority        = "Spot"
  eviction_policy = "Delete"
  spot_max_price  = -1 # pay up to the on-demand price; never evicted for price

  auto_scaling_enabled = true
  min_count            = local.capacity.pools.batch.min_count
  max_count            = local.capacity.pools.batch.max_count
  node_count           = local.capacity.pools.batch.min_count

  node_labels = { workload = "batch" }
  node_taints = ["kubernetes.azure.com/scalesetpriority=spot:NoSchedule"] # AKS adds this anyway

  tags = local.tags

  lifecycle {
    ignore_changes = [
      node_count,                                           # the autoscaler owns this
      node_labels["kubernetes.azure.com/scalesetpriority"], # AKS adds it to every spot pool
    ]
  }
}

# You: cluster admin through Entra ID.
resource "azurerm_role_assignment" "aks_me" {
  scope                = azurerm_kubernetes_cluster.main.id
  role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"
  principal_id         = data.azurerm_client_config.current.object_id
}
