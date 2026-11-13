resource "azurerm_monitor_action_group" "operations" {
  name                = "${local.name}-operations"
  resource_group_name = azurerm_resource_group.this.name
  short_name          = "energyops"
  email_receiver {
    name          = "operations"
    email_address = var.alert_email
  }
}
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "health" {
  count                 = var.stage == "apps" ? 1 : 0
  name                  = "${local.name}-missing-health"
  resource_group_name   = azurerm_resource_group.this.name
  location              = var.location
  scopes                = [azurerm_log_analytics_workspace.this.id]
  severity              = 1
  evaluation_frequency  = "PT15M"
  window_duration       = "PT1H"
  skip_query_validation = true # Console table may not exist until first job execution.
  criteria {
    query                   = <<-KQL
      ContainerAppConsoleLogs_CL
      | where ContainerGroupName_s startswith "${local.name}-monitor-"
      | where Log_s contains "PLATFORM_HEALTH_OK"
    KQL
    time_aggregation_method = "Count"
    operator                = "LessThan"
    threshold               = 1
    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }
  action { action_groups = [azurerm_monitor_action_group.operations.id] }
}
