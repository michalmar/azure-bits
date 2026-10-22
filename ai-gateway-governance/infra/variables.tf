variable "subscription_id" {
  type        = string
  description = "Authorized Azure subscription for the demo."
}

variable "resource_group_name" {
  type        = string
  default     = "rg-ai-gateway-governance-demo"
  description = "Dedicated resource group for the demo."
}

variable "location" {
  type        = string
  default     = "swedencentral"
  description = "Azure region for all demo resources."
}

variable "foundry_account_scope_id" {
  type        = string
  description = "Scope of the existing Foundry account for role assignments."
}

variable "foundry_openai_endpoint" {
  type        = string
  default     = "https://demo-swe.openai.azure.com"
  description = "HTTPS OpenAI endpoint of the existing Foundry resource for the direct baseline."
}

variable "direct_large_deployment" {
  type        = string
  default     = "gpt-6.1-sol"
  description = "Name of the existing deployment called directly in the baseline."
}

variable "gateway_endpoint" {
  type        = string
  default     = "https://aigw-swe.swedencentral-01.ai.gateway.azure.com"
  description = "HTTPS endpoint of the existing Azure API Management AI Gateway."
}

variable "gateway_primary_model" {
  type        = string
  default     = "demo-swe/gpt-6-1-sol"
  description = "Primary model alias configured on the AI Gateway."
}

variable "gateway_fallback_model" {
  type        = string
  default     = "demo-swe/gpt-6-luna"
  description = "Fallback model alias configured on the AI Gateway."
}

variable "gateway_app_key_name" {
  type        = string
  default     = "demo-azure-bits"
  description = "Non-secret label for the application's primary AI Gateway runtime key."
}

variable "gateway_burst_key_name" {
  type        = string
  default     = "demo-azure-bits-burst"
  description = "Non-secret label for the rate-limit burst AI Gateway runtime key."
}

variable "container_image" {
  type        = string
  default     = ""
  description = "Immutable image reference supplied after the ACR build."
}

variable "app_name" {
  type        = string
  default     = "ai-gateway-governance-demo"
  description = "Container App name."
}

variable "environment_name" {
  type        = string
  default     = "acae-aigw-governance-demo"
  description = "Container Apps Express environment name."
}

variable "identity_name" {
  type        = string
  default     = "uami-aigw-governance-demo"
  description = "User-assigned managed identity name."
}

variable "acr_name" {
  type        = string
  default     = "acraigwgovdemo"
  description = "Globally unique Azure Container Registry name."
}

variable "vnet_name" {
  type        = string
  default     = "vnet-aigw-governance-demo"
  description = "Virtual network name."
}

variable "apps_subnet_name" {
  type        = string
  default     = "apps"
  description = "Delegated subnet used by Azure Container Apps."
}

variable "vnet_cidr" {
  type        = string
  default     = "10.78.0.0/24"
  description = "VNet address space."
}

variable "apps_subnet_cidr" {
  type        = string
  default     = "10.78.0.0/27"
  description = "Delegated subnet address range."
}
