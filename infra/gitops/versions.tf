terraform {
  required_version = ">= 1.10, < 2.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.3"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 3.3"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.27"
    }
  }

  # Partial backend config, like platform and compute:
  #   terraform init "-backend-config=../state.tfbackend"
  backend "azurerm" {
    key = "gitops.tfstate"
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

# Talk to AKS as yourself: local accounts are disabled, so tokens come from kubelogin
# using your `az login` session (install with `az aks install-cli`). Your IP must be in
# the cluster's authorized ranges. 6dae42f8-... is the fixed AKS Entra server app ID.
locals {
  kube = {
    host                   = data.azurerm_kubernetes_cluster.main.kube_config[0].host
    cluster_ca_certificate = base64decode(data.azurerm_kubernetes_cluster.main.kube_config[0].cluster_ca_certificate)
    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "kubelogin"
      args        = ["get-token", "--login", "azurecli", "--server-id", "6dae42f8-4368-4678-94ff-3960e28e3630"]
    }
  }
}

provider "kubernetes" {
  host                   = local.kube.host
  cluster_ca_certificate = local.kube.cluster_ca_certificate
  exec {
    api_version = local.kube.exec.api_version
    command     = local.kube.exec.command
    args        = local.kube.exec.args
  }
}

provider "helm" {
  kubernetes = {
    host                   = local.kube.host
    cluster_ca_certificate = local.kube.cluster_ca_certificate
    exec                   = local.kube.exec
  }
}

# Cloudflare: reads CLOUDFLARE_API_TOKEN from the environment (never put it in a file).
# Needs Zone DNS Edit on the zone plus Account Cloudflare Tunnel and Access edit rights.
provider "cloudflare" {}
