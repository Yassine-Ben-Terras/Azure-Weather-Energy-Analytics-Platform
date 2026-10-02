mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id = "11111111-1111-1111-1111-111111111111"
      object_id = "22222222-2222-2222-2222-222222222222"
    }
  }
}
mock_provider "random" {}

variables {
  entsoe_api_token    = "test-only"
  airflow_admin_email = "test@example.invalid"
  alert_email         = "test@example.invalid"
  image_tag           = "test-commit"
}

run "foundation" {
  command = plan
  assert {
    condition = azurerm_resource_group.this.location == "switzerlandnorth" && azurerm_container_app_environment.this.location == "switzerlandnorth" && azurerm_postgresql_flexible_server.this.location == "switzerlandnorth" && azurerm_storage_account.raw.location == "switzerlandnorth"
    error_message = "Default deployment region must be Switzerland North across compute, database and storage."
  }
  assert {
    condition     = length(azurerm_container_app.app) == 0 && length(azurerm_container_app_job.job) == 0
    error_message = "Foundation must not pull unpublished images or start applications."
  }
  assert {
    condition     = azurerm_postgresql_flexible_server.this.public_network_access_enabled == false
    error_message = "PostgreSQL must have no public endpoint."
  }
  assert {
    condition     = azurerm_storage_account.raw.is_hns_enabled == false && azurerm_storage_account.raw.shared_access_key_enabled == false
    error_message = "Use plain Blob storage with identity authentication."
  }
}

run "bootstrap" {
  command = plan
  variables { stage = "bootstrap" }
  assert {
    condition     = length(azurerm_container_app.app) == 0 && length(azurerm_container_app_job.job) == 1
    error_message = "Bootstrap must create only the migration job, before applications."
  }
  assert {
    condition = contains([for env in azurerm_container_app_job.job["bootstrap"].template[0].container[0].env : "${env.name}=${coalesce(env.value, "secret")}"], "CONNECTION_CHECK_MAX_COUNT=0")
    error_message = "Bootstrap must run before Airflow database connection checks."
  }
}

run "applications" {
  command = plan
  variables { stage = "apps" }
  assert {
    condition     = length(azurerm_container_app.app) == 3 && length(azurerm_container_app_job.job) == 2
    error_message = "Require scheduler, webserver, API, bootstrap and monitoring."
  }
  assert {
    condition     = azurerm_container_app.app["scheduler"].template[0].min_replicas == 1
    error_message = "The Airflow scheduler must never scale to zero."
  }
  assert {
    condition     = azurerm_container_app_environment.this.internal_load_balancer_enabled
    error_message = "Application ingress must stay private."
  }
  assert {
    condition     = toset([for secret in azurerm_container_app.app["api"].secret : secret.name]) == toset(["api-db", "api-token"])
    error_message = "The API must not receive pipeline, administrator or storage secrets."
  }
  assert {
    condition = contains([for env in azurerm_container_app.app["scheduler"].template[0].container[0].env : "${env.name}=${coalesce(env.value, "secret")}"], "AIRFLOW__LOGGING__REMOTE_BASE_LOG_FOLDER=wasb://energy-weather")
    error_message = "Azure task logging must use a wasb:// remote path."
  }
  assert {
    condition = contains([for env in azurerm_container_app_job.job["monitor"].template[0].container[0].env : "${env.name}=${coalesce(env.value, "secret")}"], "CONNECTION_CHECK_MAX_COUNT=0")
    error_message = "The monitor must not depend on an Airflow metadata database."
  }
}
