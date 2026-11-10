terraform {
  required_version = ">= 1.6"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
    azapi   = { source = "azure/azapi", version = "~> 2.0" }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}
provider "azapi" {
  subscription_id = var.subscription_id
}

variable "subscription_id" {
  type    = string
  default = "7bc68c68-f434-49ad-ab3e-b883ec39da86"
}
variable "resource_group_name" {
  type    = string
  default = "rg-foundry-copilot-harness-demo"
}
variable "container_image" { type = string }
variable "agent_principal_id" { type = string }
variable "approve_role_assignments" {
  type    = bool
  default = false
}

locals {
  shared_group = "rg-foundry-mai-audio-demo"
  project_id   = "/subscriptions/${var.subscription_id}/resourceGroups/rg-ai/providers/Microsoft.CognitiveServices/accounts/demo-swe/projects/demo-swe-prj"
}

data "azurerm_user_assigned_identity" "existing" {
  name                = "foundry-mai-audio-identity"
  resource_group_name = local.shared_group
}
data "azurerm_container_registry" "existing" {
  name                = "maiaudio7bc68"
  resource_group_name = local.shared_group
}
data "azapi_resource" "storage" {
  type                   = "Microsoft.Storage/storageAccounts@2023-05-01"
  name                   = "maiaudio7bc68"
  parent_id              = "/subscriptions/${var.subscription_id}/resourceGroups/${local.shared_group}"
  response_export_values = ["properties.publicNetworkAccess", "properties.allowSharedKeyAccess", "properties.allowBlobPublicAccess"]
}
data "azapi_resource" "environment" {
  type                   = "Microsoft.App/managedEnvironments@2026-03-02-preview"
  name                   = "foundry-mai-audio-env"
  parent_id              = "/subscriptions/${var.subscription_id}/resourceGroups/${local.shared_group}"
  response_export_values = ["properties.environmentMode"]
}

resource "azurerm_resource_group" "demo" {
  name     = var.resource_group_name
  location = "swedencentral"
  tags     = { purpose = "copilot-harness-demo" }
}

resource "azurerm_role_assignment" "agent_files" {
  count              = var.approve_role_assignments ? 1 : 0
  scope              = local.project_id
  role_definition_id = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/53ca6127-db72-4b80-b1b0-d745d6d5456d"
  principal_id       = var.agent_principal_id
  principal_type     = "ServicePrincipal"
}

resource "azapi_resource" "app" {
  type                      = "Microsoft.App/containerApps@2026-03-02-preview"
  name                      = "foundry-copilot-harness-demo"
  parent_id                 = azurerm_resource_group.demo.id
  location                  = azurerm_resource_group.demo.location
  schema_validation_enabled = false
  response_export_values    = ["properties.configuration.ingress.fqdn"]
  body = {
    identity = {
      type = "UserAssigned"
      userAssignedIdentities = {
        "${data.azurerm_user_assigned_identity.existing.id}" = {}
      }
    }
    properties = {
      managedEnvironmentId = data.azapi_resource.environment.id
      configuration = {
        activeRevisionsMode = "Single"
        ingress             = { external = true, targetPort = 8000, transport = "Http", allowInsecure = false }
        registries = [{
          server   = data.azurerm_container_registry.existing.login_server
          identity = data.azurerm_user_assigned_identity.existing.id
        }]
      }
      template = {
        containers = [{
          name      = "web"
          image     = var.container_image
          resources = { cpu = 0.5, memory = "1Gi" }
          env = [
            { name = "APP_ENV", value = "production" },
            { name = "LIVE_DEMO_ENABLED", value = "false" },
            { name = "LOCAL_DEV", value = "false" },
            { name = "UPLOAD_API_ENABLED", value = "false" },
          ]
          probes = [
            for kind in ["Startup", "Readiness", "Liveness"] : {
              type             = kind
              httpGet          = { path = "/healthz", port = 8000 }
              periodSeconds    = 10
              failureThreshold = 30
            }
          ]
        }]
        scale = {
          minReplicas = 0
          maxReplicas = 1
          rules       = [{ name = "http", http = { metadata = { concurrentRequests = "10" } } }]
        }
      }
    }
  }
  lifecycle {
    # Runtime secrets and reader settings are configured without putting secrets in state.
    ignore_changes = [body]
    precondition {
      condition     = data.azapi_resource.environment.output.properties.environmentMode == "Express"
      error_message = "The shared environment must actually be Container Apps Express."
    }
    precondition {
      condition     = data.azapi_resource.storage.output.properties.publicNetworkAccess == "Disabled" && !data.azapi_resource.storage.output.properties.allowSharedKeyAccess && !data.azapi_resource.storage.output.properties.allowBlobPublicAccess
      error_message = "Shared storage must remain private and key-disabled."
    }
  }
}

output "app_id" { value = azapi_resource.app.id }
output "origin" { value = "https://${azapi_resource.app.output.properties.configuration.ingress.fqdn}" }
output "shared_identity_id" { value = data.azurerm_user_assigned_identity.existing.id }
