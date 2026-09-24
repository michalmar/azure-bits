variable "subscription_id" {
  type        = string
  description = "Authorized Azure subscription for the demo."
}

variable "resource_group_name" {
  type        = string
  default     = "rg-foundry-gpt-live-demo"
  description = "Dedicated resource group for the demo."
}

variable "location" {
  type        = string
  default     = "swedencentral"
  description = "Azure region for all demo resources."
}

variable "name_prefix" {
  type        = string
  default     = "foundry-gpt-live-demo"
  description = "Stable prefix used for resource names."
}

variable "foundry_account_scope_id" {
  type        = string
  description = "Scope of the existing Foundry account for role assignments."
}

variable "azure_openai_endpoint" {
  type        = string
  description = "HTTPS OpenAI endpoint of the existing Foundry resource."
}

variable "live_deployment" {
  type        = string
  default     = "gpt-live-1"
  description = "Name of the existing GPT-Live model deployment."
}

variable "container_image" {
  type        = string
  default     = ""
  description = "Immutable image reference for the app, supplied after the ACR build."
}

variable "app_name" {
  type        = string
  default     = "foundry-gpt-live-demo"
  description = "Container App name."
}

variable "environment_name" {
  type        = string
  default     = "acae-foundry-gpt-live-demo"
  description = "Container Apps Express environment name."
}

variable "identity_name" {
  type        = string
  default     = "uami-foundry-gpt-live-demo"
  description = "User-assigned managed identity name."
}

variable "acr_name" {
  type        = string
  default     = "acrfoundrygptlive"
  description = "Azure Container Registry name."
}

variable "vnet_name" {
  type        = string
  default     = "vnet-foundry-gpt-live-demo"
  description = "Virtual network name."
}

variable "apps_subnet_name" {
  type        = string
  default     = "apps"
  description = "Delegated subnet used by Azure Container Apps."
}

variable "vnet_cidr" {
  type        = string
  default     = "10.74.0.0/24"
  description = "VNet address space."
}

variable "apps_subnet_cidr" {
  type        = string
  default     = "10.74.0.0/27"
  description = "Delegated subnet address range."
}
