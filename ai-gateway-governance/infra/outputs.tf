output "resource_group_name" {
  value = azurerm_resource_group.demo.name
}

output "location" {
  value = azurerm_resource_group.demo.location
}

output "acr_name" {
  value = azurerm_container_registry.acr.name
}

output "acr_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "identity_id" {
  value = azurerm_user_assigned_identity.demo.id
}

output "identity_client_id" {
  value = azurerm_user_assigned_identity.demo.client_id
}

output "identity_principal_id" {
  value = azurerm_user_assigned_identity.demo.principal_id
}

output "managed_environment_id" {
  value = azapi_resource.express_environment.id
}

output "container_app_id" {
  value = local.container_image_configured ? azapi_resource.container_app[0].id : null
}
