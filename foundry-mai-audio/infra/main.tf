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
variable "subscription_id" { type = string }
variable "resource_group_name" {
  type    = string
  default = "rg-foundry-mai-audio-demo"
}
variable "prefix" {
  type    = string
  default = "foundry-mai-audio"
}
variable "location" {
  type    = string
  default = "swedencentral"
}
variable "storage_account_name" { type = string }
variable "registry_name" { type = string }
variable "foundry_account_id" { type = string }
variable "foundry_project_url" { type = string }
variable "container_image" {
  type    = string
  default = ""
}

resource "azurerm_resource_group" "demo" {
  name     = var.resource_group_name
  location = var.location
  tags     = { purpose = "mai-audio-demo" }
}
resource "azurerm_virtual_network" "demo" {
  name                = "${var.prefix}-vnet"
  location            = var.location
  resource_group_name = azurerm_resource_group.demo.name
  address_space       = ["10.76.0.0/24"]
}
resource "azurerm_subnet" "apps" {
  name                 = "apps"
  resource_group_name  = azurerm_resource_group.demo.name
  virtual_network_name = azurerm_virtual_network.demo.name
  address_prefixes     = ["10.76.0.0/27"]
  delegation {
    name = "container-apps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}
resource "azurerm_subnet" "private" {
  name                              = "private-endpoints"
  resource_group_name               = azurerm_resource_group.demo.name
  virtual_network_name              = azurerm_virtual_network.demo.name
  address_prefixes                  = ["10.76.0.32/28"]
  private_endpoint_network_policies = "Disabled"
}
resource "azapi_resource" "media" {
  type      = "Microsoft.Storage/storageAccounts@2023-05-01"
  name      = var.storage_account_name
  parent_id = azurerm_resource_group.demo.id
  location  = var.location
  body = {
    kind = "StorageV2"
    sku  = { name = "Standard_LRS" }
    properties = {
      accessTier                   = "Cool"
      publicNetworkAccess          = "Disabled"
      allowBlobPublicAccess        = false
      allowSharedKeyAccess         = false
      defaultToOAuthAuthentication = true
      supportsHttpsTrafficOnly     = true
      minimumTlsVersion            = "TLS1_2"
      networkAcls                  = { defaultAction = "Deny", bypass = "None" }
    }
  }
}
resource "azapi_resource" "container" {
  type      = "Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01"
  name      = "site"
  parent_id = "${azapi_resource.media.id}/blobServices/default"
  body      = { properties = { publicAccess = "None" } }
}
resource "azurerm_private_dns_zone" "blob" {
  name                = "privatelink.blob.core.windows.net"
  resource_group_name = azurerm_resource_group.demo.name
}
resource "azurerm_private_dns_zone_virtual_network_link" "blob" {
  name                  = "${var.prefix}-dns"
  resource_group_name   = azurerm_resource_group.demo.name
  private_dns_zone_name = azurerm_private_dns_zone.blob.name
  virtual_network_id    = azurerm_virtual_network.demo.id
}
resource "azurerm_private_endpoint" "blob" {
  name                = "${var.prefix}-blob"
  resource_group_name = azurerm_resource_group.demo.name
  location            = var.location
  subnet_id           = azurerm_subnet.private.id
  private_service_connection {
    name                           = "blob"
    private_connection_resource_id = azapi_resource.media.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "blob"
    private_dns_zone_ids = [azurerm_private_dns_zone.blob.id]
  }
}
resource "azurerm_user_assigned_identity" "demo" {
  name                = "${var.prefix}-identity"
  resource_group_name = azurerm_resource_group.demo.name
  location            = var.location
}
resource "azurerm_container_registry" "demo" {
  name                = var.registry_name
  resource_group_name = azurerm_resource_group.demo.name
  location            = var.location
  sku                 = "Basic"
  admin_enabled       = false
}
resource "azurerm_role_assignment" "pull" {
  scope                = azurerm_container_registry.demo.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.demo.principal_id
  principal_type       = "ServicePrincipal"
}
resource "azurerm_role_assignment" "reader" {
  scope                = azapi_resource.container.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.demo.principal_id
  principal_type       = "ServicePrincipal"
}
resource "azurerm_role_assignment" "speech" {
  scope                = var.foundry_account_id
  role_definition_name = "Cognitive Services Speech User"
  principal_id         = azurerm_user_assigned_identity.demo.principal_id
  principal_type       = "ServicePrincipal"
}
resource "azurerm_role_assignment" "foundry" {
  scope                = var.foundry_account_id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_user_assigned_identity.demo.principal_id
  principal_type       = "ServicePrincipal"
}
resource "azapi_resource" "environment" {
  type                      = "Microsoft.App/managedEnvironments@2026-03-02-preview"
  name                      = "${var.prefix}-env"
  parent_id                 = azurerm_resource_group.demo.id
  location                  = var.location
  schema_validation_enabled = false
  body = { properties = {
    environmentMode     = "Express"
    publicNetworkAccess = "Enabled"
    vnetConfiguration   = { infrastructureSubnetId = azurerm_subnet.apps.id, internal = false }
  } }
}
resource "azapi_resource" "app" {
  count                     = var.container_image != "" ? 1 : 0
  type                      = "Microsoft.App/containerApps@2026-03-02-preview"
  name                      = "${var.prefix}-demo"
  parent_id                 = azurerm_resource_group.demo.id
  location                  = var.location
  schema_validation_enabled = false
  depends_on                = [azurerm_role_assignment.pull, azurerm_role_assignment.reader, azurerm_private_endpoint.blob]
  body = {
    identity = {
      type                   = "UserAssigned"
      userAssignedIdentities = { "${azurerm_user_assigned_identity.demo.id}" = {} }
    }
    properties = {
      managedEnvironmentId = azapi_resource.environment.id
      configuration = {
        activeRevisionsMode = "Single"
        ingress             = { external = true, targetPort = 8000, transport = "Http", allowInsecure = false }
        registries          = [{ server = azurerm_container_registry.demo.login_server, identity = azurerm_user_assigned_identity.demo.id }]
      }
      template = {
        containers = [{
          name      = "web"
          image     = var.container_image
          resources = { cpu = 0.5, memory = "1Gi" }
          env = [
            { name = "STORAGE_ACCOUNT_NAME", value = azapi_resource.media.name },
            { name = "BLOB_CONTAINER_NAME", value = "site" },
            { name = "AZURE_CLIENT_ID", value = azurerm_user_assigned_identity.demo.client_id },
            { name = "FOUNDRY_PROJECT_URL", value = var.foundry_project_url },
            { name = "FOUNDRY_ACCOUNT_ID", value = var.foundry_account_id },
            { name = "TRANSCRIBE_DEPLOYMENT", value = "MAI-Transcribe-2-Streaming" },
            { name = "AUTH_PROVIDER", value = "none" },
            { name = "SESSION_SECRET", value = "empty-bootstrap-no-reader-authentication-enabled" },
            { name = "LIVE_AUDIO_ENABLED", value = "false" },
            { name = "UPLOAD_API_ENABLED", value = "false" },
          ]
          probes = [
            for kind in ["Startup", "Readiness", "Liveness"] : {
              type             = kind
              httpGet          = { path = "/healthz", port = 8000 }
              periodSeconds    = 5
              failureThreshold = 12
            }
          ]
        }]
        scale = {
          minReplicas = 0
          maxReplicas = 1
          rules       = [{ name = "http", http = { metadata = { concurrentRequests = "20" } } }]
        }
      }
    }
  }
  # Entra/session secrets and post-bootstrap runtime settings are managed via ARM.
  lifecycle { ignore_changes = [body] }
}
output "foundation" {
  value = {
    subscriptionId      = var.subscription_id
    resourceGroup       = azurerm_resource_group.demo.name
    appId               = "${azurerm_resource_group.demo.id}/providers/Microsoft.App/containerApps/${var.prefix}-demo"
    containerId         = azapi_resource.container.id
    storageId           = azapi_resource.media.id
    identityId          = azurerm_user_assigned_identity.demo.id
    identityPrincipalId = azurerm_user_assigned_identity.demo.principal_id
    identityClientId    = azurerm_user_assigned_identity.demo.client_id
    registryName        = azurerm_container_registry.demo.name
    registryServer      = azurerm_container_registry.demo.login_server
    environmentId       = azapi_resource.environment.id
    storageAccountName  = azapi_resource.media.name
    foundryAccountId    = var.foundry_account_id
  }
}
