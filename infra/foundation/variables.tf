variable "subscription_id" { type = string }
variable "tenant_id" { type = string }
variable "operator_object_id" { type = string }
variable "location" {
  type    = string
  default = "eastus2"
}
variable "name" {
  type    = string
  default = "openings-prod"
}
variable "resource_suffix" {
  description = "Globally unique lowercase alphanumeric suffix for storage, registry and vault."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9]{4,10}$", var.resource_suffix))
    error_message = "Use 4–10 lowercase letters or digits."
  }
}
variable "kubernetes_version" {
  type    = string
  default = "1.36"
}
