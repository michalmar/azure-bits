output "resource_group_name" {
  value = azurerm_resource_group.demo.name
}

output "acr_name" {
  value = azurerm_container_registry.acr.name
}

output "acr_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "key_vault_id" {
  value = azurerm_key_vault.demo.id
}

output "key_vault_name" {
  value = azurerm_key_vault.demo.name
}

output "key_vault_uri" {
  value = azurerm_key_vault.demo.vault_uri
}

output "identity_client_id" {
  value = azurerm_user_assigned_identity.demo.client_id
}

output "managed_environment_id" {
  value = azapi_resource.express_environment.id
}

output "container_app_id" {
  value = local.app_configured ? azapi_resource.container_app[0].id : null
}
