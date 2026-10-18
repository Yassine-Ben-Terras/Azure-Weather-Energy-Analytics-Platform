locals {
  warehouse_env = {
    WAREHOUSE_HOST        = azurerm_postgresql_flexible_server.this.fqdn
    WAREHOUSE_PORT        = "5432"
    WAREHOUSE_DB          = "energy_weather"
    WAREHOUSE_USER        = "pipeline"
    WAREHOUSE_SSLMODE     = "verify-full"
    WAREHOUSE_SSLROOTCERT = "/etc/ssl/certs/ca-certificates.crt"
  }
  airflow_env = {
    AIRFLOW_DB_HOST                                          = azurerm_postgresql_flexible_server.this.fqdn
    AIRFLOW_DB_PORT                                          = "5432"
    AIRFLOW_DB_DB                                            = "airflow"
    AIRFLOW_DB_USER                                          = "airflow"
    AIRFLOW_DB_SSLMODE                                       = "verify-full"
    AIRFLOW__CORE__EXECUTOR                                  = "LocalExecutor"
    AIRFLOW__CORE__PARALLELISM                               = "3"
    AIRFLOW__CORE__LOAD_EXAMPLES                             = "false"
    AIRFLOW__SCHEDULER__ENABLE_HEALTH_CHECK                  = "true"
    AIRFLOW__LOGGING__REMOTE_LOGGING                         = "true"
    AIRFLOW__LOGGING__REMOTE_BASE_LOG_FOLDER                 = "wasb://energy-weather"
    AIRFLOW__LOGGING__REMOTE_LOG_CONN_ID                     = "azure_logs"
    AIRFLOW__AZURE_REMOTE_LOGGING__REMOTE_WASB_LOG_CONTAINER = "airflow-logs"
  }
  storage_env = {
    AZURE_STORAGE_ACCOUNT_URL = azurerm_storage_account.raw.primary_blob_endpoint
    AZURE_STORAGE_CONTAINER   = "raw-data"
  }
  airflow_secrets = {
    AIRFLOW_DB_PASSWORD            = "airflow-db"
    AIRFLOW__CORE__FERNET_KEY      = "fernet"
    AIRFLOW__WEBSERVER__SECRET_KEY = "webserver-key"
  }
  workloads = {
    scheduler = {
      image   = "${azurerm_container_registry.this.login_server}/airflow:${var.image_tag}"
      args    = ["scheduler"]
      cpu     = 2
      memory  = "4Gi"
      port    = 8974
      path    = "/health"
      ingress = false
      env     = merge(local.airflow_env, local.warehouse_env, local.storage_env, { INGEST_LOOKBACK_DAYS = "7", MAX_SOURCE_AGE_HOURS = "24" })
      secrets = merge(local.airflow_secrets, { WAREHOUSE_PASSWORD = "warehouse", ENTSOE_API_TOKEN = "entsoe-token" })
    }
    webserver = {
      image   = "${azurerm_container_registry.this.login_server}/airflow:${var.image_tag}"
      args    = ["webserver"]
      cpu     = 1
      memory  = "2Gi"
      port    = 8080
      path    = "/health"
      ingress = true
      env     = local.airflow_env
      secrets = local.airflow_secrets
    }
    api = {
      image   = "${azurerm_container_registry.this.login_server}/api:${var.image_tag}"
      args    = null
      cpu     = 0.5
      memory  = "1Gi"
      port    = 8000
      path    = "/health"
      ingress = true
      env     = merge(local.warehouse_env, { WAREHOUSE_USER = "api_reader" })
      secrets = { WAREHOUSE_PASSWORD = "api-db", API_AUTH_TOKEN = "api-token" }
    }
    bootstrap = {
      image   = "${azurerm_container_registry.this.login_server}/airflow:${var.image_tag}"
      args    = ["python", "/opt/project/scripts/bootstrap.py"]
      cpu     = 1
      memory  = "2Gi"
      port    = 0
      path    = ""
      ingress = false
      env = merge(local.airflow_env, local.warehouse_env, {
        ADMIN_HOST                       = azurerm_postgresql_flexible_server.this.fqdn
        ADMIN_USER                       = "platform_admin"
        ADMIN_DB                         = "postgres"
        ADMIN_SSLMODE                    = "verify-full"
        BOOTSTRAP_STORAGE                = "false"
        CONNECTION_CHECK_MAX_COUNT       = "0"
        AIRFLOW_ADMIN_USER               = "admin"
        AIRFLOW_ADMIN_EMAIL              = var.airflow_admin_email
        AIRFLOW__LOGGING__REMOTE_LOGGING = "false"
      })
      secrets = merge(local.airflow_secrets, {
        ADMIN_PASSWORD       = "postgres-admin", WAREHOUSE_PASSWORD = "warehouse"
        METABASE_DB_PASSWORD = "metabase-db", API_DB_PASSWORD = "api-db"
        BI_DB_PASSWORD       = "bi-db", AIRFLOW_ADMIN_PASSWORD = "airflow-admin"
      })
    }
    monitor = {
      image   = "${azurerm_container_registry.this.login_server}/airflow:${var.image_tag}"
      args    = ["python", "/opt/project/scripts/monitor.py"]
      cpu     = 0.25
      memory  = "0.5Gi"
      port    = 0
      path    = ""
      ingress = false
      env     = merge(local.warehouse_env, { WAREHOUSE_USER = "api_reader", CONNECTION_CHECK_MAX_COUNT = "0" })
      secrets = { WAREHOUSE_PASSWORD = "api-db" }
    }
  }
  secret_grants = merge([for app, config in local.workloads : {
    for secret in toset(values(config.secrets)) : "${app}-${secret}" => { app = app, secret = secret }
  }]...)
}
resource "azurerm_user_assigned_identity" "app" {
  for_each            = local.workloads
  name                = "${local.name}-${each.key}"
  resource_group_name = azurerm_resource_group.this.name
  location            = var.location
}
resource "azurerm_role_assignment" "pull" {
  for_each             = local.workloads
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app[each.key].principal_id
}
resource "azurerm_role_assignment" "secret" {
  for_each             = local.secret_grants
  scope                = "${azurerm_key_vault.this.id}/secrets/${each.value.secret}"
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app[each.value.app].principal_id
  depends_on           = [azurerm_key_vault_secret.this]
}
resource "azurerm_role_assignment" "bronze" {
  scope                = azurerm_storage_container.this["raw-data"].resource_manager_id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.app["scheduler"].principal_id
}
resource "azurerm_role_assignment" "logs" {
  for_each             = { scheduler = "Storage Blob Data Contributor", webserver = "Storage Blob Data Reader" }
  scope                = azurerm_storage_container.this["airflow-logs"].resource_manager_id
  role_definition_name = each.value
  principal_id         = azurerm_user_assigned_identity.app[each.key].principal_id
}
resource "azurerm_container_app" "app" {
  for_each                     = { for key, value in local.workloads : key => value if var.stage == "apps" && !contains(["bootstrap", "monitor"], key) }
  name                         = "${local.name}-${each.key}"
  resource_group_name          = azurerm_resource_group.this.name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app[each.key].id]
  }
  dynamic "registry" {
    for_each = [1]
    content {
      server   = azurerm_container_registry.this.login_server
      identity = azurerm_user_assigned_identity.app[each.key].id
    }
  }
  dynamic "secret" {
    for_each = toset(values(each.value.secrets))
    content {
      name                = secret.value
      key_vault_secret_id = azurerm_key_vault_secret.this[secret.value].versionless_id
      identity            = azurerm_user_assigned_identity.app[each.key].id
    }
  }
  dynamic "ingress" {
    for_each = each.value.ingress ? [1] : []
    content {
      external_enabled           = true # VNet-only: environment has an INTERNAL load balancer.
      allow_insecure_connections = false
      target_port                = each.value.port
      traffic_weight {
        latest_revision = true
        percentage      = 100
      }
    }
  }
  template {
    min_replicas = 1
    max_replicas = 1
    container {
      name   = each.key
      image  = each.value.image
      args   = each.value.args
      cpu    = each.value.cpu
      memory = each.value.memory
      dynamic "env" {
        for_each = merge(each.value.env, {
          AZURE_CLIENT_ID = azurerm_user_assigned_identity.app[each.key].client_id
          }, contains(["scheduler", "webserver"], each.key) ? {
          AIRFLOW_CONN_AZURE_LOGS = jsonencode({ conn_type = "wasb", host = azurerm_storage_account.raw.primary_blob_endpoint,
          extra = { managed_identity_client_id = azurerm_user_assigned_identity.app[each.key].client_id } })
        } : {})
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = each.value.secrets
        content {
          name        = env.key
          secret_name = env.value
        }
      }
      startup_probe {
        transport               = "HTTP"
        port                    = each.value.port
        path                    = each.value.path
        interval_seconds        = 30
        failure_count_threshold = 10
        timeout                 = 5
      }
      liveness_probe {
        transport               = "HTTP"
        port                    = each.value.port
        path                    = each.value.path
        interval_seconds        = 30
        failure_count_threshold = 5
        timeout                 = 5
      }
      readiness_probe {
        transport        = "HTTP"
        port             = each.value.port
        path             = each.key == "api" ? "/ready" : each.value.path
        interval_seconds = 30
        timeout          = 5
      }
    }
  }
  depends_on = [azurerm_role_assignment.pull, azurerm_role_assignment.secret, azurerm_role_assignment.bronze, azurerm_role_assignment.logs, azurerm_postgresql_flexible_server_configuration.extensions]
  lifecycle {
    # CD owns image releases after Terraform creates the workload.
    ignore_changes = [template[0].container[0].image]
    precondition {
      condition     = var.image_tag != "unpublished"
      error_message = "Publish both images and set their immutable image_tag first."
    }
  }
}
resource "azurerm_container_app_job" "job" {
  for_each                     = { for key, value in local.workloads : key => value if(key == "bootstrap" && var.stage != "foundation") || (key == "monitor" && var.stage == "apps") }
  name                         = "${local.name}-${each.key}"
  resource_group_name          = azurerm_resource_group.this.name
  location                     = var.location
  container_app_environment_id = azurerm_container_app_environment.this.id
  replica_timeout_in_seconds   = each.key == "bootstrap" ? 1800 : 120
  workload_profile_name        = "Consumption"
  replica_retry_limit          = 1
  dynamic "manual_trigger_config" {
    for_each = each.key == "bootstrap" ? [1] : []
    content {
      parallelism              = 1
      replica_completion_count = 1
    }
  }
  dynamic "schedule_trigger_config" {
    for_each = each.key == "monitor" ? [1] : []
    content {
      cron_expression          = "*/15 * * * *"
      parallelism              = 1
      replica_completion_count = 1
    }
  }
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app[each.key].id]
  }
  registry {
    server   = azurerm_container_registry.this.login_server
    identity = azurerm_user_assigned_identity.app[each.key].id
  }
  dynamic "secret" {
    for_each = toset(values(each.value.secrets))
    content {
      name                = secret.value
      key_vault_secret_id = azurerm_key_vault_secret.this[secret.value].versionless_id
      identity            = azurerm_user_assigned_identity.app[each.key].id
    }
  }
  template {
    container {
      name   = each.key
      image  = each.value.image
      args   = each.value.args
      cpu    = each.value.cpu
      memory = each.value.memory
      dynamic "env" {
        for_each = each.value.env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = each.value.secrets
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }
  depends_on = [azurerm_role_assignment.secret, azurerm_role_assignment.pull, azurerm_postgresql_flexible_server_database.db]
  lifecycle {
    # CD owns image releases after Terraform creates the workload.
    ignore_changes = [template[0].container[0].image]
    precondition {
      condition     = var.image_tag != "unpublished"
      error_message = "Publish the Airflow image before provisioning the bootstrap job."
    }
  }
}
