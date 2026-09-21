locals {
  tags = {
    project = "foundry-image-models"
    purpose = "demo"
  }
  container_image_configured = trimspace(var.container_image) != ""
}

resource "azurerm_resource_group" "demo" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.tags
}

resource "azurerm_virtual_network" "demo" {
  name                = var.vnet_name
  location            = azurerm_resource_group.demo.location
  resource_group_name = azurerm_resource_group.demo.name
  address_space       = [var.vnet_cidr]
  tags                = local.tags
}

resource "azurerm_subnet" "apps" {
  name                 = var.apps_subnet_name
  resource_group_name  = azurerm_resource_group.demo.name
  virtual_network_name = azurerm_virtual_network.demo.name
  address_prefixes     = [var.apps_subnet_cidr]

  delegation {
    name = "container-apps"

    service_delegation {
      name = "Microsoft.App/environments"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
      ]
    }
  }
}

resource "azurerm_user_assigned_identity" "demo" {
  name                = var.identity_name
  location            = azurerm_resource_group.demo.location
  resource_group_name = azurerm_resource_group.demo.name
  tags                = local.tags
}

resource "azurerm_container_registry" "acr" {
  name                = var.acr_name
  location            = azurerm_resource_group.demo.location
  resource_group_name = azurerm_resource_group.demo.name
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.demo.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "foundry_reader" {
  scope                = var.foundry_account_scope_id
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.demo.principal_id
  principal_type       = "ServicePrincipal"
}

moved {
  from = azurerm_role_assignment.foundry_openai_user
  to   = azurerm_role_assignment.foundry_cognitive_services_user
}

resource "azurerm_role_assignment" "foundry_cognitive_services_user" {
  scope                = var.foundry_account_scope_id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_user_assigned_identity.demo.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azapi_resource" "express_environment" {
  type      = "Microsoft.App/managedEnvironments@2026-03-02-preview"
  name      = var.environment_name
  location  = azurerm_resource_group.demo.location
  parent_id = azurerm_resource_group.demo.id

  schema_validation_enabled = false
  tags                      = local.tags

  body = {
    properties = {
      environmentMode     = "Express"
      publicNetworkAccess = "Enabled"
      vnetConfiguration = {
        infrastructureSubnetId = azurerm_subnet.apps.id
        internal               = false
      }
    }
  }
}

resource "azapi_resource" "container_app" {
  count     = local.container_image_configured ? 1 : 0
  type      = "Microsoft.App/containerApps@2026-03-02-preview"
  name      = var.app_name
  location  = azurerm_resource_group.demo.location
  parent_id = azurerm_resource_group.demo.id

  schema_validation_enabled = false
  tags                      = local.tags

  body = {
    identity = {
      type = "UserAssigned"
      userAssignedIdentities = {
        "${azurerm_user_assigned_identity.demo.id}" = {}
      }
    }
    properties = {
      managedEnvironmentId = azapi_resource.express_environment.id
      configuration = {
        activeRevisionsMode = "Single"
        ingress = {
          external      = true
          targetPort    = 8000
          transport     = "Http"
          allowInsecure = false
        }
        registries = [
          {
            server   = azurerm_container_registry.acr.login_server
            identity = azurerm_user_assigned_identity.demo.id
          }
        ]
      }
      template = {
        containers = [
          {
            name  = "web"
            image = var.container_image
            resources = {
              cpu    = 0.5
              memory = "1Gi"
            }
            env = [
              { name = "APP_ENV", value = "production" },
              { name = "AUTH_ENABLED", value = "true" },
              { name = "AUTH_PROVIDER", value = var.auth_provider },
              { name = "AZURE_AI_ENDPOINT", value = var.azure_ai_endpoint },
              { name = "AZURE_CLIENT_ID", value = azurerm_user_assigned_identity.demo.client_id },
              { name = "ENTRA_TENANT_ID", value = var.entra_tenant_id },
              { name = "FOUNDRY_SUBSCRIPTION_ID", value = var.foundry_subscription_id },
              { name = "FOUNDRY_RESOURCE_GROUP", value = var.foundry_resource_group },
              { name = "FOUNDRY_ACCOUNT_NAME", value = var.foundry_account_name },
              { name = "FOUNDRY_LOCATION", value = var.foundry_location },
              { name = "FOUNDRY_BASE_URL", value = var.foundry_base_url },
              { name = "PUBLIC_BASE_URL", value = var.public_base_url },
            ]
            probes = [
              {
                type = "Startup"
                httpGet = {
                  path = "/healthz"
                  port = 8000
                }
                periodSeconds    = 5
                failureThreshold = 6
              },
              {
                type = "Readiness"
                httpGet = {
                  path = "/healthz"
                  port = 8000
                }
                periodSeconds    = 5
                failureThreshold = 6
              },
              {
                type = "Liveness"
                httpGet = {
                  path = "/healthz"
                  port = 8000
                }
                periodSeconds    = 10
                failureThreshold = 3
              },
            ]
          }
        ]
        scale = {
          minReplicas = 0
          maxReplicas = 1
          rules = [
            {
              name = "http"
              http = {
                metadata = {
                  concurrentRequests = "20"
                }
              }
            }
          ]
        }
      }
    }
  }
}
