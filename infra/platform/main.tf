# Network and the research data store. Collected research is the asset here (each run
# costs provider calls), so the account is zone-redundant, soft-deletes for 30 days,
# is locked against deletion and has prevent_destroy.
data "azurerm_client_config" "current" {}

locals {
  tags = {
    project    = var.project
    component  = "platform"
    managed_by = "terraform"
  }
}

# Storage account names are global across Azure, so they get a random suffix.
resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

resource "azurerm_resource_group" "platform" {
  name     = "rg-${var.project}-platform"
  location = var.location
  tags     = local.tags
}

resource "azurerm_virtual_network" "main" {
  name                = "vnet-${var.project}"
  resource_group_name = azurerm_resource_group.platform.name
  location            = azurerm_resource_group.platform.location
  address_space       = ["10.84.0.0/16"]
  tags                = local.tags
}

# AKS nodes. With Azure CNI Overlay pods get IPs from a separate range, so a /22 is
# plenty. Service endpoints let the nodes through the storage, Key Vault and Azure OpenAI firewalls
# without public IP rules or private endpoints.
resource "azurerm_subnet" "aks" {
  name                 = "snet-aks"
  resource_group_name  = azurerm_resource_group.platform.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.84.0.0/22"]
  service_endpoints    = ["Microsoft.Storage", "Microsoft.KeyVault", "Microsoft.CognitiveServices"]
}

# ADLS Gen2 for the Iceberg warehouse and the catalog database backups.
resource "azurerm_storage_account" "research" {
  name                     = "st${var.project}${random_string.suffix.result}" # <= 24 chars
  resource_group_name      = azurerm_resource_group.platform.name
  location                 = azurerm_resource_group.platform.location
  account_kind             = "StorageV2"
  account_tier             = "Standard"
  account_replication_type = "ZRS"
  access_tier              = "Hot"
  is_hns_enabled           = true # can only be set at creation

  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  shared_access_key_enabled       = false # Entra ID and user-delegation SAS only
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false

  # Deny by default, no trusted-service bypass, AKS subnet allowed. Your IP is added
  # by hand in Azure and Terraform never touches the IP list (infra/README.md).
  network_rules {
    default_action             = "Deny"
    virtual_network_subnet_ids = [azurerm_subnet.aks.id]
    bypass                     = ["None"]
  }

  # Versioning isn't supported with a hierarchical namespace; soft delete is.
  blob_properties {
    delete_retention_policy {
      days = var.soft_delete_days
    }
    container_delete_retention_policy {
      days = var.soft_delete_days
    }
  }

  tags = local.tags

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [network_rules[0].ip_rules] # IPs are set by hand in Azure
  }
}

# Iceberg tables, written through Lakekeeper's vended credentials.
resource "azurerm_storage_container" "research" {
  name                  = "research"
  storage_account_id    = azurerm_storage_account.research.id # created via ARM, not the data plane
  container_access_type = "private"
  lifecycle { prevent_destroy = true }
}

# Barman base backups and WAL of the catalog database.
resource "azurerm_storage_container" "catalog_backups" {
  name                  = "catalog-backups"
  storage_account_id    = azurerm_storage_account.research.id
  container_access_type = "private"
  lifecycle { prevent_destroy = true }
}

# Argo Workflows' archived step logs.
resource "azurerm_storage_container" "workflow_logs" {
  name                  = "workflow-logs"
  storage_account_id    = azurerm_storage_account.research.id
  container_access_type = "private"
}

# Read the data as yourself (az login). Can take a few minutes after apply.
resource "azurerm_role_assignment" "research_me" {
  scope                = azurerm_storage_account.research.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Stops the account being deleted from the portal or CLI too.
resource "azurerm_management_lock" "research" {
  name       = "do-not-delete"
  scope      = azurerm_storage_account.research.id
  lock_level = "CanNotDelete"
  notes      = "Collected opening research"
}
