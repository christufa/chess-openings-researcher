# Platform outputs: location, storage account, containers, AKS subnet.
data "terraform_remote_state" "platform" {
  backend = "azurerm"
  config = {
    resource_group_name  = var.state_resource_group_name
    storage_account_name = var.state_storage_account_name
    container_name       = var.state_container_name
    key                  = "platform.tfstate"
    use_azuread_auth     = true
  }
}

data "azurerm_client_config" "current" {}

locals {
  platform = data.terraform_remote_state.platform.outputs
  capacity = jsondecode(file("${path.module}/../capacity.json"))

  # Namespaces whose service accounts receive Azure identities (deploy/ charts).
  catalog_namespace  = "openings-catalog"
  research_namespace = "openings-research"

  container_scope = "${local.platform.storage_account_id}/blobServices/default/containers"

  tags = {
    project    = var.project
    component  = "compute"
    managed_by = "terraform"
  }
}

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

resource "azurerm_resource_group" "compute" {
  name     = "rg-${var.project}-compute"
  location = local.platform.location
  tags     = local.tags
}
