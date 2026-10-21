terraform {
  required_version = ">= 1.10, < 2.0"
  backend "azurerm" {}
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.0"
    }
  }
}
variable "subscription_id" { type = string }
variable "tenant_id" { type = string }
variable "resource_group_name" { type = string }
variable "cluster_name" { type = string }
variable "admission_client_id" { type = string }
variable "registry_login_server" { type = string }
provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id
}
data "azurerm_kubernetes_cluster" "main" {
  name                = var.cluster_name
  resource_group_name = var.resource_group_name
}
provider "helm" {
  kubernetes = {
    host                   = data.azurerm_kubernetes_cluster.main.kube_config[0].host
    cluster_ca_certificate = base64decode(data.azurerm_kubernetes_cluster.main.kube_config[0].cluster_ca_certificate)
    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "kubelogin"
      args        = ["get-token", "--login", "azurecli", "--server-id", "6dae42f8-4368-4678-94ff-3960e28e3630", "--tenant-id", var.tenant_id]
    }
  }
}

locals {
  controllers = {
    argocd           = { chart = "argo-cd", repository = "https://argoproj.github.io/argo-helm", version = "10.10.5", namespace = "argocd", values = "argocd.yaml" }
    workflows        = { chart = "argo-workflows", repository = "https://argoproj.github.io/argo-helm", version = "2.0.13", namespace = "argo", values = "workflows.yaml" }
    cert-manager     = { chart = "cert-manager", repository = "https://charts.jetstack.io", version = "v1.21.2", namespace = "cert-manager", values = "cert-manager.yaml" }
    cnpg             = { chart = "cloudnative-pg", repository = "https://cloudnative-pg.github.io/charts", version = "0.29.1", namespace = "cnpg-system", values = "cnpg.yaml" }
    external-secrets = { chart = "external-secrets", repository = "https://charts.external-secrets.io", version = "2.13.0", namespace = "external-secrets", values = "external-secrets.yaml" }
    kyverno          = { chart = "kyverno", repository = "https://kyverno.github.io/kyverno", version = "3.9.2", namespace = "kyverno", values = "kyverno.yaml" }
  }
}
resource "helm_release" "controllers" {
  for_each         = local.controllers
  name             = each.key
  repository       = each.value.repository
  chart            = each.value.chart
  version          = each.value.version
  namespace        = each.value.namespace
  create_namespace = true
  atomic           = true
  wait             = true
  timeout          = 900
  values = concat([file("${path.module}/../../deploy/controllers/${each.value.values}")], each.key == "kyverno" ? [yamlencode({
    admissionController = {
      podLabels = { "azure.workload.identity/use" = "true" }
      rbac = { serviceAccount = {
        name        = "openings-admission"
        annotations = { "azure.workload.identity/client-id" = var.admission_client_id }
      } }
    }
  })] : [])
  depends_on = [helm_release.namespaces]
}
resource "helm_release" "namespaces" {
  name      = "openings-namespaces"
  chart     = "${path.module}/../../deploy/namespaces"
  namespace = "default"
  atomic    = true
  wait      = true
}
resource "helm_release" "barman" {
  name       = "barman-cloud"
  repository = "https://cloudnative-pg.github.io/charts"
  chart      = "plugin-barman-cloud"
  version    = "0.8.1"
  namespace  = "cnpg-system"
  atomic     = true
  wait       = true
  timeout    = 600
  depends_on = [helm_release.controllers]
}
resource "helm_release" "gitops" {
  name       = "openings-gitops"
  chart      = "${path.module}/../../deploy/gitops"
  namespace  = "argocd"
  atomic     = true
  wait       = true
  depends_on = [helm_release.platform_base]
}
resource "helm_release" "platform_base" {
  name       = "openings-platform-base"
  chart      = "${path.module}/../../deploy/platform-base"
  namespace  = "argocd"
  atomic     = true
  wait       = true
  values     = [yamlencode({ registry = var.registry_login_server })]
  depends_on = [helm_release.controllers, helm_release.trust_manager]
}
resource "helm_release" "trust_manager" {
  name       = "trust-manager"
  repository = "https://charts.jetstack.io"
  chart      = "trust-manager"
  version    = "v0.25.0"
  namespace  = "cert-manager"
  atomic     = true
  wait       = true
  depends_on = [helm_release.controllers]
}
