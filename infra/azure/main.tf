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
resource "azurerm_virtual_network" "this" {
  name                = "${local.name}-vnet"
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
  address_space       = ["10.42.0.0/16"]
}
resource "azurerm_subnet" "apps" {
  name                 = "apps"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.42.0.0/23"]
  delegation {
    name = "container-apps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}
resource "azurerm_subnet" "postgres" {
  name                 = "postgres"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.42.2.0/24"]
  service_endpoints    = ["Microsoft.Storage"]
  delegation {
    name = "postgres"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}
resource "azurerm_private_dns_zone" "postgres" {
  name                = "${local.name}.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.this.name
}
resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "postgres"
  resource_group_name   = azurerm_resource_group.this.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.this.id
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
  backup_retention_days         = 14
  auto_grow_enabled             = true
  delegated_subnet_id           = azurerm_subnet.postgres.id
  private_dns_zone_id           = azurerm_private_dns_zone.postgres.id
  public_network_access_enabled = false
  tags                          = var.tags
  depends_on                    = [azurerm_private_dns_zone_virtual_network_link.postgres]
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
  name                           = local.name
  resource_group_name            = azurerm_resource_group.this.name
  location                       = var.location
  log_analytics_workspace_id     = azurerm_log_analytics_workspace.this.id
  infrastructure_subnet_id       = azurerm_subnet.apps.id
  internal_load_balancer_enabled = true
  # Keep Azure's infrastructure group name explicit to avoid replacement on refresh.
  infrastructure_resource_group_name = "ME_${local.name}_${azurerm_resource_group.this.name}_${var.location}"
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}
resource "azurerm_private_dns_zone" "apps" {
  name                = azurerm_container_app_environment.this.default_domain
  resource_group_name = azurerm_resource_group.this.name
}
resource "azurerm_private_dns_zone_virtual_network_link" "apps" {
  name                  = "apps"
  resource_group_name   = azurerm_resource_group.this.name
  private_dns_zone_name = azurerm_private_dns_zone.apps.name
  virtual_network_id    = azurerm_virtual_network.this.id
}
resource "azurerm_private_dns_a_record" "apps" {
  name                = "*"
  zone_name           = azurerm_private_dns_zone.apps.name
  resource_group_name = azurerm_resource_group.this.name
  ttl                 = 60
  records             = [azurerm_container_app_environment.this.static_ip_address]
}
