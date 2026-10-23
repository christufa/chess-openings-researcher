mock_provider "azurerm" {}
mock_provider "random" {}

variables {
  subscription_id = "00000000-0000-0000-0000-000000000001"
}

run "private_research_storage" {
  command = plan
  assert {
    condition = (
      azurerm_storage_account.research.network_rules[0].default_action == "Deny" &&
      azurerm_storage_account.research.network_rules[0].bypass == toset(["None"])
    )
    error_message = "Research storage must deny by default with no trusted-service bypass."
  }
  assert {
    condition     = !azurerm_storage_account.research.shared_access_key_enabled && !azurerm_storage_account.research.allow_nested_items_to_be_public
    error_message = "Research storage must be keyless and never publicly readable."
  }
  assert {
    condition     = azurerm_storage_account.research.account_replication_type == "ZRS" && azurerm_storage_account.research.blob_properties[0].delete_retention_policy[0].days >= 30
    error_message = "Collected research must survive a zone loss and accidental deletes."
  }
  assert {
    condition     = azurerm_management_lock.research.lock_level == "CanNotDelete"
    error_message = "The research account must be locked against deletion."
  }
  assert {
    condition     = contains(azurerm_subnet.aks.service_endpoints, "Microsoft.Storage") && contains(azurerm_subnet.aks.service_endpoints, "Microsoft.KeyVault")
    error_message = "AKS must reach storage and Key Vault through service endpoints."
  }
}
