terraform {
  required_version = ">= 1.10, < 2.0"
  backend "azurerm" {}
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

# Read CLOUDFLARE_API_TOKEN from the process environment, never from tfvars.
provider "cloudflare" {}
variable "zone_id" { type = string }
variable "public_ipv4" {
  type = string
  validation {
    condition     = can(cidrnetmask("${var.public_ipv4}/32"))
    error_message = "Supply the provisioned public gateway IPv4 address."
  }
}
resource "cloudflare_dns_record" "openings" {
  zone_id = var.zone_id
  name    = "openings.generops.dev"
  type    = "A"
  content = var.public_ipv4
  ttl     = 1
  proxied = true
  comment = "Managed by openings-researcher Terraform"
}
