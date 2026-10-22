mock_provider "azurerm" {}
variables {
  subscription_id    = "00000000-0000-0000-0000-000000000001"
  tenant_id          = "00000000-0000-0000-0000-000000000002"
  operator_object_id = "00000000-0000-0000-0000-000000000003"
  state_account_name = "openingsteststate"
  operator_ipv4      = "203.0.113.7"
}
run "restricted_state" {
  command = plan
  assert {
    condition     = azurerm_storage_account.state.network_rules[0].default_action == "Deny" && azurerm_storage_account.state.network_rules[0].ip_rules == toset(["203.0.113.7"])
    error_message = "Bootstrap state must permit only the explicitly configured operator address."
  }
  assert {
    condition     = !azurerm_storage_account.state.shared_access_key_enabled && azurerm_storage_account.state.blob_properties[0].versioning_enabled
    error_message = "State requires Entra authentication and recoverable versions."
  }
  assert {
    condition     = azurerm_management_lock.state.lock_level == "CanNotDelete"
    error_message = "State account must be protected by a deletion lock."
  }
}
