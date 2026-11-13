variable "enable_network_probe" {
  description = "Temporary outbound-network probe; disable after validating app and job connectivity."
  type        = bool
  default     = true
}
resource "azurerm_container_app_job" "network_probe" {
  count                        = var.enable_network_probe ? 1 : 0
  name                         = "${local.name}-network-probe"
  resource_group_name          = azurerm_resource_group.this.name
  location                     = var.location
  container_app_environment_id = azurerm_container_app_environment.this.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 120
  replica_retry_limit          = 0
  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }
  template {
    container {
      name    = "probe"
      image   = "docker.io/library/python:3.11-alpine"
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-c"]
      args    = ["import urllib.request; print('EGRESS_IPV4=' + urllib.request.urlopen('https://api4.ipify.org', timeout=30).read().decode(), flush=True)"]
    }
  }
}
output "probe_outbound_ipv4_addresses" {
  description = "Candidate runtime egress set; verify against execution and all apps/jobs before relying on it."
  value       = try(azurerm_container_app_job.network_probe[0].outbound_ip_addresses, [])
}

