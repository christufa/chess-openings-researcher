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

  # Partial backend config: the state account's name stays out of this public repo.
  # The rest comes from ../state.tfbackend (gitignored; copy state.tfbackend.example):
  #   terraform init "-backend-config=../state.tfbackend"
  backend "azurerm" {
    key = "platform.tfstate"
  }
}

provider "azurerm" {
  features {
    storage {
      # Manage storage only through Azure Resource Manager, never the blob endpoint,
      # so the firewall can deny everything without breaking Terraform.
      data_plane_available = false
    }
  }
  subscription_id     = var.subscription_id
  storage_use_azuread = true
}
