mock_provider "azurerm" {
  mock_resource "azurerm_kubernetes_cluster" {
    defaults = {
      kubelet_identity = [{
        client_id                 = "00000000-0000-0000-0000-000000000004"
        object_id                 = "00000000-0000-0000-0000-000000000005"
        user_assigned_identity_id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/kubelet"
      }]
    }
  }
}
variables {
  subscription_id    = "00000000-0000-0000-0000-000000000001"
  tenant_id          = "00000000-0000-0000-0000-000000000002"
  operator_object_id = "00000000-0000-0000-0000-000000000003"
  resource_suffix    = "testprod"
  state_account_id   = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/state/providers/Microsoft.Storage/storageAccounts/openingsstate"
}
run "private_foundation" {
  command = plan
  assert {
    condition = (
      azurerm_kubernetes_cluster.main.default_node_pool[0].vm_size == "Standard_D4ds_v6" &&
      azurerm_kubernetes_cluster_node_pool.research.vm_size == "Standard_D8ds_v6" &&
      output.capacity_requirements.startup == 36 &&
      output.capacity_requirements.maximum_with_surge == 116
    )
    error_message = "The node pools and quota requirements must agree with the approved Ddsv6 sizing."
  }
  assert {
    condition     = azurerm_kubernetes_cluster.main.private_cluster_enabled && azurerm_kubernetes_cluster.main.local_account_disabled && !azurerm_kubernetes_cluster.main.run_command_enabled
    error_message = "AKS must use a private control plane and Entra access without local admin or command bypass."
  }
  assert {
    condition     = !azurerm_storage_account.research.public_network_access_enabled && !azurerm_storage_account.research.shared_access_key_enabled && !azurerm_storage_account.research.allow_nested_items_to_be_public
    error_message = "Research storage must remain private and keyless."
  }
  assert {
    condition     = !azurerm_container_registry.main.admin_enabled && !azurerm_container_registry.main.public_network_access_enabled
    error_message = "Registry must remain private without administrator credentials."
  }
  assert {
    condition     = azurerm_federated_identity_credential.publisher.subject == "repo:christufa/openings-researcher:environment:production" && azurerm_role_assignment.publish.role_definition_name == "AcrPush"
    error_message = "Publisher trust must require the protected production environment and registry-only publishing role."
  }
  assert {
    condition     = azurerm_federated_identity_credential.catalog.subject == "system:serviceaccount:openings-catalog:lakekeeper"
    error_message = "Only the catalog service account may obtain the Azure catalog identity."
  }
}
