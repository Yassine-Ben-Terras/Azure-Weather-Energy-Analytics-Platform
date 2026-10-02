output "resource_group_name" { value = azurerm_resource_group.this.name }
output "location" { value = azurerm_resource_group.this.location }
output "acr_name" { value = azurerm_container_registry.this.name }
output "acr_login_server" { value = azurerm_container_registry.this.login_server }
output "postgres_fqdn" { value = azurerm_postgresql_flexible_server.this.fqdn }
output "storage_account_name" { value = azurerm_storage_account.raw.name }
output "key_vault_name" { value = azurerm_key_vault.this.name }
output "virtual_network_id" { value = azurerm_virtual_network.this.id }
output "private_urls" {
  description = "Accessible only from the VNet (or a connected VPN/peered network with DNS resolution)."
  value       = { for name, app in azurerm_container_app.app : name => "https://${app.ingress[0].fqdn}" if name != "scheduler" }
}
output "bootstrap_job_name" { value = try(azurerm_container_app_job.job["bootstrap"].name, null) }
output "monitor_job_name" { value = try(azurerm_container_app_job.job["monitor"].name, null) }
output "container_app_names" { value = { for name, app in azurerm_container_app.app : name => app.name } }
