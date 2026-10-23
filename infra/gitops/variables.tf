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

# ---- Entry from the internet (Cloudflare Tunnel + Access, edge.tf) ----

variable "domain" {
  description = "Cloudflare zone the hostnames live in"
  type        = string
  default     = "generops.dev"
}

variable "hostname_prefix" {
  description = "<prefix> is the public explorer; <prefix>-cd and <prefix>-flows are private"
  type        = string
  default     = "chess-openings"
}

variable "cloudflare_account_id" {
  description = "Cloudflare account ID (zone Overview page, right sidebar)"
  type        = string
}

variable "cloudflare_zone_id" {
  description = "Zone ID of var.domain (zone Overview page, right sidebar)"
  type        = string
}

variable "cloudflare_team_name" {
  description = "Zero Trust team name: <team>.cloudflareaccess.com"
  type        = string
}

variable "access_allowed_emails" {
  description = "Who may sign in to the private hostnames: your Entra sign-in email"
  type        = list(string)
}

variable "access_identity_provider_id" {
  description = "Cloudflare Access identity provider to sign in with (lichess-delta-kube's Microsoft Entra ID provider)"
  type        = string
}
