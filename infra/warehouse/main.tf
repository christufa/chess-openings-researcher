terraform {
  required_version = ">= 1.10, < 2.0"
  backend "azurerm" {}
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}
provider "azurerm" {
  features {}
  subscription_id     = var.subscription_id
  tenant_id           = var.tenant_id
  storage_use_azuread = true
}
variable "subscription_id" { type = string }
variable "tenant_id" { type = string }
variable "storage_account_id" { type = string }
variable "catalog_principal_id" { type = string }
variable "backup_principal_id" { type = string }

# Run from the private network after foundation is applied. The executing
# operator needs Storage Blob Data Contributor on this dedicated account.
resource "azurerm_storage_container" "research" {
  name                  = "research"
  storage_account_id    = var.storage_account_id
  container_access_type = "private"
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "catalog_data" {
  scope                = "${var.storage_account_id}/blobServices/default/containers/${azurerm_storage_container.research.name}"
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = var.catalog_principal_id
}
output "research_container" { value = azurerm_storage_container.research.name }

resource "azurerm_storage_container" "backups" {
  name                  = "catalog-backups"
  storage_account_id    = var.storage_account_id
  container_access_type = "private"
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "backup_data" {
  scope                = "${var.storage_account_id}/blobServices/default/containers/${azurerm_storage_container.backups.name}"
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = var.backup_principal_id
}
