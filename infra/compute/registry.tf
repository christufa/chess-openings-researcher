# Image registry. Basic tier, Entra ID only. The images hold only code from this
# public repository, never research data, so the registry needs no private network.
resource "azurerm_container_registry" "main" {
  name                = "acr${var.project}${random_string.suffix.result}" # letters and digits only
  resource_group_name = azurerm_resource_group.compute.name
  location            = azurerm_resource_group.compute.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.tags
}

# Lets you push from your PC after `az acr login`.
resource "azurerm_role_assignment" "acr_me" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Lets the cluster's nodes pull images.
resource "azurerm_role_assignment" "acr_aks" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.kubelet.principal_id
}

# --- CI identity (GitHub Actions OIDC) ---------------------------------------------
# The images workflow signs in with a GitHub OIDC token and pushes images. Azure only
# accepts tokens for this repository's (and chess-engines') main branch, and the identity can do nothing
# but push to the registry. No stored secrets; GitHub-hosted runners.
resource "azurerm_user_assigned_identity" "ci" {
  name                = "id-${var.project}-ci"
  resource_group_name = azurerm_resource_group.compute.name
  location            = azurerm_resource_group.compute.location
  tags                = local.tags
}

resource "azurerm_federated_identity_credential" "ci_main" {
  name                      = "github-main"
  user_assigned_identity_id = azurerm_user_assigned_identity.ci.id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = "https://token.actions.githubusercontent.com"
  subject                   = "repo:${var.github_oidc_repository}:ref:refs/heads/main"
}

# christufa/chess-engines publishes the shared engine API image to this registry too,
# from its own main branch only (its images.yml).
resource "azurerm_federated_identity_credential" "ci_engines_main" {
  name                      = "github-chess-engines-main"
  user_assigned_identity_id = azurerm_user_assigned_identity.ci.id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = "https://token.actions.githubusercontent.com"
  subject                   = "repo:${var.github_oidc_engines_repository}:ref:refs/heads/main"
}

resource "azurerm_role_assignment" "ci_acr" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.ci.principal_id
}

# Weekly ACR task (works on Basic): drop commit-SHA tags older than 30 days, keeping
# the newest 10 per image, then manifests left without tags.
resource "azurerm_container_registry_task" "purge" {
  name                  = "purge-old-images"
  container_registry_id = azurerm_container_registry.main.id
  tags                  = local.tags

  platform {
    os = "Linux"
  }

  encoded_step {
    task_content = base64encode(<<-EOT
      version: v1.1.0
      steps:
        - cmd: acr purge --filter 'openings-.*:^[0-9a-f]{40}$' --filter 'chess-engines:^[0-9a-f]{40}$' --ago 30d --keep 10 --untagged
          disableWorkingDirectoryOverride: true
          timeout: 3600
    EOT
    )
  }

  timer_trigger {
    name     = "weekly"
    schedule = "0 7 * * 0" # Sundays 07:00 UTC
    enabled  = true
  }
}
