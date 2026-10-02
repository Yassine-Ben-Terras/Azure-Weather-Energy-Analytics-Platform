variable "project_prefix" {
  type    = string
  default = "ewplat"
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,9}$", var.project_prefix))
    error_message = "Use 3-10 lowercase letters/digits, starting with a letter."
  }
}
variable "environment" {
  type    = string
  default = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Use dev, staging or prod."
  }
}
variable "location" {
  description = "Azure region for all regional application resources."
  type        = string
  default     = "switzerlandnorth"
}
variable "stage" {
  description = "foundation -> publish images -> bootstrap -> run bootstrap job -> apps. Never downgrade a live stage."
  type        = string
  default     = "foundation"
  validation {
    condition     = contains(["foundation", "bootstrap", "apps"], var.stage)
    error_message = "Use foundation, bootstrap or apps."
  }
}
variable "image_tag" {
  description = "Immutable commit tag shared by Airflow and API images."
  type        = string
  default     = "unpublished"
  validation {
    condition     = can(regex("^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}$", var.image_tag)) && var.image_tag != "latest"
    error_message = "Use an immutable image tag; latest is forbidden."
  }
}
variable "postgres_sku_name" {
  description = "Initial shared DB capacity; benchmark the hourly workload before production."
  type        = string
  default     = "B_Standard_B2s"
}
variable "postgres_zone" {
  description = "Optional PostgreSQL availability zone; null lets Azure choose."
  type        = string
  default     = null
  validation {
    condition     = var.postgres_zone == null ? true : contains(["1", "2", "3"], var.postgres_zone)
    error_message = "postgres_zone must be null, 1, 2 or 3."
  }
}
variable "postgres_storage_mb" {
  type    = number
  default = 32768
}
variable "entsoe_api_token" {
  description = "Sensitive; persisted in Terraform state. Supply via TF_VAR_entsoe_api_token."
  type        = string
  sensitive   = true
}
variable "airflow_admin_email" {
  type = string
}
variable "alert_email" {
  description = "Operations email receiving Azure Monitor alerts."
  type        = string
}
variable "tags" {
  type    = map(string)
  default = { project = "weather-energy-platform" }
}
