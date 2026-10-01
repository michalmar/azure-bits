variable "subscription_id" {
  type        = string
  description = "Authorized Azure subscription for the demo."
}

variable "resource_group_name" {
  type        = string
  default     = "rg-foundry-flex-demo"
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

variable "azure_openai_endpoint" {
  type        = string
  description = "HTTPS OpenAI endpoint of the existing Foundry resource."
}

variable "model_deployment" {
  type        = string
  default     = "gpt-5.6-sol"
  description = "Name of the existing GPT-5.6 Sol deployment."
}

variable "container_image" {
  type        = string
  default     = ""
  description = "Immutable image reference supplied after the ACR build."
}

variable "app_name" {
  type        = string
  default     = "foundry-flex-demo"
  description = "Container App name."
}

variable "environment_name" {
  type        = string
  default     = "acae-foundry-flex-demo"
  description = "Container Apps Express environment name."
}

variable "identity_name" {
  type        = string
  default     = "uami-foundry-flex-demo"
  description = "User-assigned managed identity name."
}

variable "acr_name" {
  type        = string
  default     = "acrfoundryflexdemo"
  description = "Globally unique Azure Container Registry name."
}

variable "vnet_name" {
  type        = string
  default     = "vnet-foundry-flex-demo"
  description = "Virtual network name."
}

variable "apps_subnet_name" {
  type        = string
  default     = "apps"
  description = "Delegated subnet used by Azure Container Apps."
}

variable "vnet_cidr" {
  type        = string
  default     = "10.76.0.0/24"
  description = "VNet address space."
}

variable "apps_subnet_cidr" {
  type        = string
  default     = "10.76.0.0/27"
  description = "Delegated subnet address range."
}
