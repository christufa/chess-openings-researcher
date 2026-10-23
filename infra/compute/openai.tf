# Azure OpenAI for extraction and review, with no keys: key authentication is disabled,
# and the research worker signs in as its workload identity (the `workflows` identity,
# federated to openings-research:openings-worker) with "Cognitive Services OpenAI User".
# Only the AKS subnet gets through the network rules (service endpoint); your IP can be
# added by hand like the other firewalls.
# DataZoneStandard keeps processing inside the US data zone.
variable "openai_model" {
  description = "Model and deployment name (the worker's --model default)"
  type        = string
  default     = "gpt-5.4-mini"
}

variable "openai_model_version" {
  type    = string
  default = "2026-03-17"
}

variable "openai_capacity" {
  description = "Deployment capacity in thousands of tokens per minute"
  type        = number
  default     = 50
}

resource "azurerm_cognitive_account" "openai" {
  name                  = "oai-${var.project}-${random_string.suffix.result}"
  resource_group_name   = azurerm_resource_group.compute.name
  location              = azurerm_resource_group.compute.location
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "oai-${var.project}-${random_string.suffix.result}" # required for Entra ID sign-in
  local_auth_enabled    = false                                               # no API keys at all

  public_network_access_enabled = true # reachable only as network_acls allow
  network_acls {
    default_action = "Deny"
    ip_rules       = []
    virtual_network_rules {
      subnet_id = local.platform.aks_subnet_id
    }
  }

  tags = local.tags

  lifecycle {
    ignore_changes = [network_acls[0].ip_rules] # your IP is set by hand in Azure
  }
}

resource "azurerm_cognitive_deployment" "research" {
  name                   = var.openai_model
  cognitive_account_id   = azurerm_cognitive_account.openai.id
  version_upgrade_option = "NoAutoUpgrade" # change models deliberately, through this file

  model {
    format  = "OpenAI"
    name    = var.openai_model
    version = var.openai_model_version
  }

  sku {
    name     = "DataZoneStandard"
    capacity = var.openai_capacity
  }
}

resource "azurerm_role_assignment" "worker_openai" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.workload["workflows"].principal_id
}
