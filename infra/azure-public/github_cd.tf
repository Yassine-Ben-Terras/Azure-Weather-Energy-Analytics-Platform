variable "github_repository" {
  description = "Optional owner/repository trusted for CD. Null leaves CD identity disabled."
  type        = string
  default     = null
  validation {
    condition     = var.github_repository == null ? true : can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "Use owner/repository, without a URL."
  }
}

resource "azurerm_user_assigned_identity" "github_cd" {
  count               = var.github_repository == null ? 0 : 1
  name                = "${local.name}-github-cd"
  location            = var.location
  resource_group_name = azurerm_resource_group.this.name
}

resource "azurerm_federated_identity_credential" "github_cd" {
  count               = var.github_repository == null ? 0 : 1
  name                = "github-azure-production"
  resource_group_name = azurerm_resource_group.this.name
  parent_id           = azurerm_user_assigned_identity.github_cd[0].id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = "repo:${var.github_repository}:environment:azure-production"
}

resource "azurerm_role_assignment" "github_cd_registry" {
  count                = var.github_repository == null ? 0 : 1
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.github_cd[0].principal_id
}

resource "azurerm_role_assignment" "github_cd_read" {
  count                = var.github_repository == null ? 0 : 1
  scope                = azurerm_resource_group.this.id
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.github_cd[0].principal_id
}

resource "azurerm_role_assignment" "github_cd_apps" {
  for_each             = var.github_repository == null ? {} : azurerm_container_app.app
  scope                = each.value.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.github_cd[0].principal_id
}

resource "azurerm_role_assignment" "github_cd_jobs" {
  for_each             = var.github_repository == null ? {} : azurerm_container_app_job.job
  scope                = each.value.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.github_cd[0].principal_id
}

output "github_cd_client_id" {
  value = try(azurerm_user_assigned_identity.github_cd[0].client_id, null)
}
