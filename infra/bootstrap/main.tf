variable "subscription_id" { type = string }
variable "tenant_id" { type = string }
variable "operator_object_id" { type = string }
variable "location" {
  type    = string
  default = "eastus2"
}
variable "state_account_name" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.state_account_name))
    error_message = "Use an Azure storage account name (3–24 lowercase letters/digits)."
  }
}
variable "operator_ipv4" {
  description = "Current public operator IPv4. Explicitly update this when the operator address changes."
  type        = string
  validation {
    condition     = can(cidrnetmask("${var.operator_ipv4}/32"))
    error_message = "Supply a single IPv4 address, not an unrestricted network."
  }
}
locals {
  tags = { application = "openings-researcher", environment = "production", component = "state", managed_by = "terraform" }
}
resource "azurerm_resource_group" "state" {
  name     = "rg-openings-prod-state"
  location = var.location
  tags     = local.tags
  lifecycle { prevent_destroy = true }
}
resource "azurerm_storage_account" "state" {
  name                            = var.state_account_name
  resource_group_name             = azurerm_resource_group.state.name
  location                        = var.location
  account_tier                    = "Standard"
  account_replication_type        = "ZRS"
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false
  min_tls_version                 = "TLS1_2"
  network_rules {
    default_action = "Deny"
    bypass         = ["None"]
    ip_rules       = [var.operator_ipv4]
  }
  blob_properties {
    versioning_enabled = true
    delete_retention_policy { days = 30 }
    container_delete_retention_policy { days = 30 }
  }
  tags = local.tags
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "operator" {
  scope                = azurerm_storage_account.state.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = var.operator_object_id
}
resource "azurerm_storage_container" "state" {
  name                  = "tfstate"
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
  depends_on            = [azurerm_role_assignment.operator]
  lifecycle { prevent_destroy = true }
}
resource "azurerm_management_lock" "state" {
  name       = "protect-terraform-state"
  scope      = azurerm_storage_account.state.id
  lock_level = "CanNotDelete"
  notes      = "Terraform state recovery requires deliberate lock removal."
}
output "backend" {
  value = {
    resource_group_name  = azurerm_resource_group.state.name
    storage_account_name = azurerm_storage_account.state.name
    container_name       = azurerm_storage_container.state.name
    use_azuread_auth     = true
    subscription_id      = var.subscription_id
    tenant_id            = var.tenant_id
  }
}
output "state_account_id" { value = azurerm_storage_account.state.id }
