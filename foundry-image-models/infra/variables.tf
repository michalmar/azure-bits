variable "subscription_id" {
  type        = string
  description = "Authorized Azure subscription for the demo."
}

variable "resource_group_name" {
  type        = string
  default     = "rg-foundry-image-models-demo"
  description = "Dedicated resource group for the demo."
}

variable "location" {
  type        = string
  default     = "swedencentral"
  description = "Azure region for all demo resources."
}

variable "name_prefix" {
  type        = string
  default     = "foundry-image-models-demo"
  description = "Stable prefix used for resource names."
}

variable "foundry_account_scope_id" {
  type        = string
  description = "Scope of the existing Foundry account for role assignments."
}

variable "foundry_subscription_id" {
  type        = string
  description = "Subscription metadata surfaced to the container app."
}

variable "foundry_resource_group" {
  type        = string
  description = "Resource-group metadata surfaced to the container app."
}

variable "foundry_account_name" {
  type        = string
  description = "Foundry account metadata surfaced to the container app."
}

variable "foundry_location" {
  type        = string
  default     = "swedencentral"
  description = "Foundry location metadata surfaced to the container app."
}

variable "foundry_base_url" {
  type        = string
  description = "Foundry base URL surfaced to the container app."
}

variable "azure_ai_endpoint" {
  type        = string
  description = "Endpoint used by the container app at runtime."
}

variable "entra_tenant_id" {
  type        = string
  description = "Tenant ID used for the Entra OIDC configuration."
}

variable "container_image" {
  type        = string
  default     = ""
  description = "Immutable image reference for the app, supplied after the ACR build."
}

variable "public_base_url" {
  type        = string
  default     = ""
  description = "Public origin for the live app; configured after the app FQDN is known."
}

variable "auth_provider" {
  type        = string
  default     = "entra"
  description = "Auth provider advertised to the app."
}

variable "app_name" {
  type        = string
  default     = "foundry-image-models-demo"
  description = "Container App name."
}

variable "environment_name" {
  type        = string
  default     = "acae-foundry-image-models-demo"
  description = "Container Apps Express environment name."
}

variable "identity_name" {
  type        = string
  default     = "uami-foundry-image-models-demo"
  description = "User-assigned managed identity name."
}

variable "acr_name" {
  type        = string
  default     = "acrfoundryimagedemo"
  description = "Azure Container Registry name."
}

variable "vnet_name" {
  type        = string
  default     = "vnet-foundry-image-models-demo"
  description = "Virtual network name."
}

variable "apps_subnet_name" {
  type        = string
  default     = "apps"
  description = "Delegated subnet used by Azure Container Apps."
}

variable "vnet_cidr" {
  type        = string
  default     = "10.72.0.0/24"
  description = "VNet address space."
}

variable "apps_subnet_cidr" {
  type        = string
  default     = "10.72.0.0/27"
  description = "Delegated subnet address range."
}
