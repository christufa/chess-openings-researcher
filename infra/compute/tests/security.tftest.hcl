mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id = "00000000-0000-0000-0000-000000000002"
      object_id = "00000000-0000-0000-0000-000000000003"
    }
  }
}
mock_provider "random" {}

override_resource {
  target = azurerm_kubernetes_cluster.main
  values = {
    oidc_issuer_url = "https://issuer.example/"
  }
}

override_data {
  target = data.terraform_remote_state.platform
  values = {
    outputs = {
      location                  = "eastus2"
      storage_account_id        = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-openings-platform/providers/Microsoft.Storage/storageAccounts/stopenings"
      research_container        = "research"
      catalog_backups_container = "catalog-backups"
      workflow_logs_container   = "workflow-logs"
      aks_subnet_id             = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-openings-platform/providers/Microsoft.Network/virtualNetworks/vnet-openings/subnets/snet-aks"
    }
  }
}

variables {
  subscription_id                = "00000000-0000-0000-0000-000000000001"
  state_resource_group_name      = "rg-openings-tfstate"
  state_storage_account_name     = "stopeningsstate"
  github_oidc_repository         = "christufa/chess-openings-researcher" # independent of any local tfvars
  github_oidc_engines_repository = "christufa/chess-engines"
}

run "lean_private_cluster" {
  command = plan
  assert {
    condition = (
      azurerm_kubernetes_cluster.main.sku_tier == "Free" &&
      azurerm_kubernetes_cluster.main.default_node_pool[0].min_count == 1 &&
      azurerm_kubernetes_cluster_node_pool.batch.priority == "Spot" &&
      azurerm_kubernetes_cluster_node_pool.batch.min_count == 0
    )
    error_message = "Idle cost must be one on-demand node; research runs on spot scaling from zero."
  }
  assert {
    condition     = azurerm_kubernetes_cluster.main.local_account_disabled && !azurerm_kubernetes_cluster.main.run_command_enabled
    error_message = "Cluster access must go through Entra ID without local admin or command bypass."
  }
  assert {
    condition     = azurerm_key_vault.main.network_acls[0].default_action == "Deny" && azurerm_key_vault.main.purge_protection_enabled
    error_message = "Key Vault must deny by default and keep the catalog encryption key recoverable."
  }
  assert {
    condition     = !azurerm_container_registry.main.admin_enabled
    error_message = "Registry must use Entra ID only."
  }
  assert {
    condition     = azurerm_federated_identity_credential.ci_main.subject == "repo:christufa/chess-openings-researcher:ref:refs/heads/main" && azurerm_role_assignment.ci_acr.role_definition_name == "AcrPush"
    error_message = "CI may only push images, and only from main."
  }
  assert {
    condition     = azurerm_federated_identity_credential.ci_engines_main.subject == "repo:christufa/chess-engines:ref:refs/heads/main"
    error_message = "chess-engines may push its image only from main."
  }
  assert {
    condition     = azurerm_kubernetes_cluster.main.workload_autoscaler_profile[0].keda_enabled
    error_message = "KEDA scales the chess-engines API."
  }
  assert {
    condition     = azurerm_federated_identity_credential.workload["catalog"].subject == "system:serviceaccount:openings-catalog:lakekeeper"
    error_message = "Only Lakekeeper may obtain the catalog identity."
  }
  assert {
    condition     = endswith(azurerm_role_assignment.workload["catalog-data"].scope, "/containers/research") && endswith(azurerm_role_assignment.workload["backup-data"].scope, "/containers/catalog-backups")
    error_message = "Data roles must be scoped to their own containers."
  }
  assert {
    condition     = !azurerm_cognitive_account.openai.local_auth_enabled && azurerm_cognitive_account.openai.network_acls[0].default_action == "Deny"
    error_message = "Azure OpenAI must have keys disabled and deny all but the AKS subnet."
  }
  assert {
    condition     = azurerm_role_assignment.worker_openai.role_definition_name == "Cognitive Services OpenAI User" && azurerm_cognitive_deployment.research.sku[0].name == "DataZoneStandard"
    error_message = "Only the worker identity may call the model, inside the US data zone."
  }
  assert {
    condition     = output.capacity_requirements["standardDASv5Family"].startup == 4 && output.capacity_requirements["lowPriorityCores"].startup == 0
    error_message = "Capacity requirements must follow infra/capacity.json."
  }
}
