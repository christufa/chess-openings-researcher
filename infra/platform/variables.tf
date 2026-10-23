variable "subscription_id" {
  description = "Azure subscription to deploy into"
  type        = string
}

variable "location" {
  description = "Azure region for every resource"
  type        = string
  default     = "eastus2"
}

variable "project" {
  description = "Short name used in resource names; lowercase letters and digits only"
  type        = string
  default     = "openings"

  validation {
    condition     = can(regex("^[a-z0-9]{3,8}$", var.project))
    error_message = "project must be 3-8 lowercase letters or digits."
  }
}

variable "soft_delete_days" {
  description = "Days deleted research blobs and containers can be recovered"
  type        = number
  default     = 30
}
