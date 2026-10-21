# The bootstrap account keeps its operator-only public firewall. This private
# endpoint gives trusted private runners access without opening it to CI IP ranges.
variable "state_account_id" {
  description = "Dedicated bootstrap state account resource ID."
  type        = string
}
resource "azurerm_private_endpoint" "state" {
  name                = "pe-${var.name}-state"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  subnet_id           = azurerm_subnet.endpoints.id
  tags                = local.tags
  private_service_connection {
    name                           = "state"
    private_connection_resource_id = var.state_account_id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.main["blob"].id]
  }
}
