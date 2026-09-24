locals {
  tags = {
    project = "foundry-speech-live-interpreter"
    purpose = "demo"
  }
  app_configured  = trimspace(var.container_image) != ""
  key_vault_scope = trimspace(var.key_vault_id) != "" ? var.key_vault_id : azurerm_key_vault.demo.id
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
  name                 = "apps"
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

data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "demo" {
  name                          = var.key_vault_name
  location                      = azurerm_resource_group.demo.location
  resource_group_name           = azurerm_resource_group.demo.name
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  purge_protection_enabled      = true
  soft_delete_retention_days    = 7
  public_network_access_enabled = false
  tags                          = local.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.demo.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "speech_user" {
  scope                = var.speech_resource_id
  role_definition_name = "Cognitive Services Speech User"
  principal_id         = azurerm_user_assigned_identity.demo.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "key_vault_secrets_user" {
  scope                = local.key_vault_scope
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.demo.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "deployer_key_vault_secrets_officer" {
  scope                = azurerm_key_vault.demo.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = var.deployer_principal_id
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
  count     = local.app_configured ? 1 : 0
  type      = "Microsoft.App/containerApps@2026-03-02-preview"
  name      = var.app_name
  location  = azurerm_resource_group.demo.location
  parent_id = azurerm_resource_group.demo.id

  schema_validation_enabled = false
  ignore_body_changes = [
    "properties.configuration.secrets",
  ]
  tags = local.tags

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
              { name = "AZURE_CLIENT_ID", value = azurerm_user_assigned_identity.demo.client_id },
              { name = "AZURE_SPEECH_RESOURCE_NAME", value = var.speech_resource_name },
              { name = "PERSONAL_VOICE_ENABLED", value = tostring(var.personal_voice_enabled) },
              { name = "AUTH_ENABLED", value = "true" },
              { name = "PUBLIC_BASE_URL", value = var.public_base_url },
              { name = "ENTRA_TENANT_ID", value = var.entra_tenant_id },
              { name = "ENTRA_CLIENT_ID", value = var.entra_client_id },
              { name = "ENTRA_CLIENT_SECRET", secretRef = "entra-client-secret" },
              { name = "SESSION_SECRET", secretRef = "session-secret" },
              { name = "ALLOWED_USERS", value = var.allowed_users },
            ]
            probes = [
              {
                type = "Startup"
                httpGet = {
                  path = "/healthz"
                  port = 8000
                }
                periodSeconds    = 5
                failureThreshold = 8
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
                  concurrentRequests = "10"
                }
              }
            }
          ]
        }
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.acr_pull,
    azurerm_role_assignment.speech_user,
    azurerm_role_assignment.key_vault_secrets_user,
  ]

}
