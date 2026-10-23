# Outputs of the stacks this one builds on.
locals {
  state_config = {
    resource_group_name  = var.state_resource_group_name
    storage_account_name = var.state_storage_account_name
    container_name       = var.state_container_name
    use_azuread_auth     = true
  }
}

data "terraform_remote_state" "platform" {
  backend = "azurerm"
  config  = merge(local.state_config, { key = "platform.tfstate" })
}

data "terraform_remote_state" "compute" {
  backend = "azurerm"
  config  = merge(local.state_config, { key = "compute.tfstate" })
}

data "azurerm_client_config" "current" {}

locals {
  platform = data.terraform_remote_state.platform.outputs
  compute  = data.terraform_remote_state.compute.outputs
}

# API endpoint and CA certificate for the kubernetes/helm providers.
data "azurerm_kubernetes_cluster" "main" {
  name                = local.compute.aks_name
  resource_group_name = local.compute.resource_group_name
}
