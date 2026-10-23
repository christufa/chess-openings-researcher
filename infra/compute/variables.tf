variable "subscription_id" {
  description = "Azure subscription to deploy into"
  type        = string
}

variable "project" {
  description = "Short name used in resource names; must match the platform stack"
  type        = string
  default     = "openings"
}

variable "kubernetes_version" {
  description = "AKS minor version; patches are applied automatically"
  type        = string
  default     = "1.36"
}

# ---- Where the platform state lives (same values as ../state.tfbackend) ----

variable "state_resource_group_name" {
  description = "Resource group of the Terraform state account (bootstrap output)"
  type        = string
}

variable "state_storage_account_name" {
  description = "Terraform state account (bootstrap output)"
  type        = string
}

variable "state_container_name" {
  description = "Container holding the state files"
  type        = string
  default     = "tfstate"
}

variable "github_oidc_repository" {
  description = "GitHub repository whose main-branch workflows may push images (owner/name)"
  type        = string
  default     = "christufa/chess-openings-researcher"
}
