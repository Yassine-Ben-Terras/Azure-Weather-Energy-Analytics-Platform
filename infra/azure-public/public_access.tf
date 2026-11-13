variable "subscription_id" { type = string }
variable "restrict_app_ingress_to_operator_ips" {
  description = "Restrict HTTPS interfaces by operator IPs. When false, Airflow login and API-key authentication remain required; PostgreSQL IP rules are unchanged."
  type        = bool
  default     = true
}
variable "operator_ipv4_addresses" {
  type    = set(string)
  default = []
  validation {
    condition     = alltrue([for ip in var.operator_ipv4_addresses : can(cidrnetmask("${ip}/32")) && ip != "0.0.0.0"])
    error_message = "Supply individual IPv4 addresses; broad Azure access is forbidden."
  }
}
variable "runtime_ipv4_addresses" {
  description = "Verified outbound IPv4 addresses of the ACA apps and jobs. Refresh when Azure changes egress."
  type        = set(string)
  default     = []
  validation {
    condition     = alltrue([for ip in var.runtime_ipv4_addresses : can(cidrnetmask("${ip}/32")) && ip != "0.0.0.0"])
    error_message = "Supply individual IPv4 addresses; broad Azure access is forbidden."
  }
}
resource "azurerm_postgresql_flexible_server_firewall_rule" "allowed" {
  for_each         = setunion(var.operator_ipv4_addresses, var.runtime_ipv4_addresses)
  name             = "allow-${replace(each.value, ".", "-")}"
  server_id        = azurerm_postgresql_flexible_server.this.id
  start_ip_address = each.value
  end_ip_address   = each.value
}
