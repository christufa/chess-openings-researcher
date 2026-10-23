variable "budget_amount" {
  description = "Monthly budget in the subscription's billing currency"
  type        = number
  default     = 150
}

variable "budget_start_date" {
  description = "First day of the first budget month (RFC 3339, first of a month)"
  type        = string
}

variable "budget_emails" {
  description = "Who receives budget alerts; set in terraform.tfvars, never in git"
  type        = list(string)
}

# Monthly budget for this project only: costs in the openings resource groups,
# including the node resource group AKS creates for its VMs. Alerts only: Azure
# budgets never stop anything. The hard limits are the node pools' max_count
# (infra/capacity.json) and your vCPU quotas.
locals {
  budget_resource_groups = [
    azurerm_resource_group.state.name,
    "rg-openings-platform",
    "rg-openings-compute",
    "rg-openings-compute-nodes", # created by AKS; holds the VMs, disks, load balancer
  ]
}

resource "azurerm_consumption_budget_subscription" "monthly" {
  name            = "budget-openings-monthly"
  subscription_id = "/subscriptions/${var.subscription_id}"
  amount          = var.budget_amount
  time_grain      = "Monthly"

  time_period {
    start_date = var.budget_start_date
  }

  filter {
    dimension {
      name   = "ResourceGroupName"
      values = local.budget_resource_groups
    }
  }

  dynamic "notification" {
    for_each = { actual50 = [50, "Actual"], actual80 = [80, "Actual"], actual100 = [100, "Actual"], forecast100 = [100, "Forecasted"] }
    content {
      enabled        = true
      threshold      = notification.value[0]
      operator       = "GreaterThanOrEqualTo"
      threshold_type = notification.value[1]
      contact_emails = var.budget_emails
    }
  }
}
