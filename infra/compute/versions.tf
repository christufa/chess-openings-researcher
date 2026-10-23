terraform {
  required_version = ">= 1.10, < 2.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Partial backend config, like platform:
  #   terraform init "-backend-config=../state.tfbackend"
  backend "azurerm" {
    key = "compute.tfstate"
  }
}

provider "azurerm" {
  features {}
  subscription_id     = var.subscription_id
  storage_use_azuread = true
}
