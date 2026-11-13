data "azurerm_client_config" "current" {}
locals {
  name = "${var.project_prefix}-${var.environment}-aca"
}
resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}
resource "azurerm_resource_group" "this" {
  name     = "${local.name}-rg"
  location = var.location
  tags     = var.tags
}
resource "azurerm_container_registry" "this" {
  name                = "${var.project_prefix}acr${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = var.tags
}
resource "random_password" "password" {
  for_each = toset(["postgres-admin", "warehouse", "airflow-db", "metabase-db", "api-db", "bi-db", "airflow-admin", "api-token", "webserver-key"])
  length   = 40
  special  = false
}
resource "random_id" "fernet" { byte_length = 32 }
resource "azurerm_postgresql_flexible_server" "this" {
  name                          = "${local.name}-pg-${random_string.suffix.result}"
  resource_group_name           = azurerm_resource_group.this.name
  location                      = var.location
  version                       = "16"
  administrator_login           = "platform_admin"
  administrator_password        = random_password.password["postgres-admin"].result
  storage_mb                    = var.postgres_storage_mb
  sku_name                      = var.postgres_sku_name
  zone                          = var.postgres_zone
  backup_retention_days         = 7
  auto_grow_enabled             = false
  public_network_access_enabled = true
  tags                          = var.tags
  lifecycle { prevent_destroy = true }
}
# Metabase creates citext during its application database migrations.
resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.this.id
  value     = "CITEXT"
}
resource "azurerm_postgresql_flexible_server_database" "db" {
  for_each  = toset(["energy_weather", "airflow", "metabase"])
  name      = each.key
  server_id = azurerm_postgresql_flexible_server.this.id
  collation = "en_US.utf8"
  charset   = "utf8"
  lifecycle { prevent_destroy = true }
}
resource "azurerm_storage_account" "raw" {
  name                            = "${var.project_prefix}raw${random_string.suffix.result}"
  resource_group_name             = azurerm_resource_group.this.name
  location                        = var.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  account_kind                    = "StorageV2"
  is_hns_enabled                  = false
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false
  allow_nested_items_to_be_public = false
  blob_properties {
    versioning_enabled = true
    delete_retention_policy { days = 14 }
    container_delete_retention_policy { days = 14 }
  }
  tags = var.tags
  lifecycle { prevent_destroy = true }
}
resource "azurerm_role_assignment" "storage_deployer" {
  scope                = azurerm_storage_account.raw.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}
resource "azurerm_storage_container" "this" {
  for_each              = toset(["raw-data", "airflow-logs"])
  name                  = each.key
  storage_account_name  = azurerm_storage_account.raw.name
  container_access_type = "private"
  depends_on            = [azurerm_role_assignment.storage_deployer]
  lifecycle { prevent_destroy = true }
}
resource "azurerm_storage_management_policy" "this" {
  storage_account_id = azurerm_storage_account.raw.id
  rule {
    name    = "expired-versions"
    enabled = true
    filters { blob_types = ["blockBlob"] }
    actions {
      version { delete_after_days_since_creation = 30 }
    }
  }
  rule {
    name    = "task-log-retention"
    enabled = true
    filters {
      blob_types   = ["blockBlob"]
      prefix_match = ["airflow-logs/"]
    }
    actions {
      base_blob { delete_after_days_since_modification_greater_than = 90 }
    }
  }
}
resource "azurerm_key_vault" "this" {
  name                       = "${var.project_prefix}-kv-${random_string.suffix.result}"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = var.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  enable_rbac_authorization  = true
  purge_protection_enabled   = true
  soft_delete_retention_days = 90
  tags                       = var.tags
}
resource "azurerm_role_assignment" "vault_deployer" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}
locals {
  secret_values = merge(
    { for key, value in random_password.password : key => value.result },
    { "entsoe-token" = var.entsoe_api_token,
    "fernet" = replace(replace(random_id.fernet.b64_std, "+", "-"), "/", "_") }
  )
}
resource "azurerm_key_vault_secret" "this" {
  for_each     = nonsensitive(toset(keys(local.secret_values)))
  name         = each.key
  value        = local.secret_values[each.key]
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [azurerm_role_assignment.vault_deployer]
}
resource "azurerm_log_analytics_workspace" "this" {
  name                = "${local.name}-logs"
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 1
}
resource "azurerm_container_app_environment" "this" {
  name                       = local.name
  resource_group_name        = azurerm_resource_group.this.name
  location                   = var.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

