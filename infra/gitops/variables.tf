variable "subscription_id" {
  description = "Azure subscription the cluster is in"
  type        = string
}

# ---- Where the other stacks' state lives (same values as ../state.tfbackend) ----

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

# ---- GitOps ----

variable "repo_url" {
  description = "Git repository Argo CD syncs from (public, so no credentials)"
  type        = string
  default     = "https://github.com/christufa/chess-openings-researcher.git"
}

variable "repo_revision" {
  description = "Branch, tag or commit Argo CD follows"
  type        = string
  default     = "main"
}

variable "argocd_chart_version" {
  description = "argo-cd Helm chart version (https://github.com/argoproj/argo-helm)"
  type        = string
  default     = "10.10.5"
}

variable "argocd_apps_chart_version" {
  description = "argocd-apps Helm chart version, used to create the root Application"
  type        = string
  default     = "2.0.6"
}
