variable "subscription_id" {
  type        = string
  description = "Authorized Azure subscription for the demo resources."
}

variable "resource_group_name" {
  type        = string
  default     = "rg-foundry-speech-interpreter-demo"
  description = "Dedicated resource group for the demo."
}

variable "location" {
  type        = string
  default     = "swedencentral"
  description = "Azure region for Container Apps Express resources."
}

variable "speech_resource_id" {
  type        = string
  description = "Resource ID of the existing Speech resource approved for Live Interpreter."
}

variable "speech_resource_name" {
  type        = string
  description = "Name of the existing Speech resource."
}

variable "deployer_principal_id" {
  type        = string
  description = "Object ID of the deploying user or service principal that writes initial Key Vault secrets."
}

variable "container_image" {
  type        = string
  default     = ""
  description = "Immutable ACR image reference. The app is created only when this is set."
}

variable "entra_tenant_id" {
  type        = string
  default     = ""
  description = "Single Entra tenant allowed to authenticate readers."
}

variable "entra_client_id" {
  type        = string
  default     = ""
  description = "Entra application client ID configured with the deployed callback URL."
}

variable "key_vault_id" {
  type        = string
  default     = ""
  description = "Optional existing Key Vault resource ID. Leave empty to use the vault created by this module."
}

variable "entra_client_secret_uri" {
  type        = string
  default     = ""
  description = "Versioned Key Vault secret URI for the Entra client secret."
}

variable "session_secret_uri" {
  type        = string
  default     = ""
  description = "Versioned Key Vault secret URI for the signed session secret."
}

variable "allowed_users" {
  type        = string
  default     = ""
  description = "Comma-separated entra:<oid> or email:<address> reader allowlist."
}

variable "public_base_url" {
  type        = string
  default     = ""
  description = "Actual HTTPS application origin used for the Entra callback."
}

variable "personal_voice_enabled" {
  type        = bool
  default     = false
  description = "Expose Personal Voice after approval is verified on the Speech resource."
}

variable "app_name" {
  type    = string
  default = "foundry-speech-interpreter"
}

variable "environment_name" {
  type    = string
  default = "acae-foundry-speech-interpreter"
}

variable "identity_name" {
  type    = string
  default = "uami-foundry-speech-interpreter"
}

variable "acr_name" {
  type    = string
  default = "acrspeechinterpreterdemo"
}

variable "key_vault_name" {
  type        = string
  default     = "kv-speech-interpreter-demo"
  description = "Key Vault name for OAuth and signed-session secrets."
}

variable "vnet_name" {
  type    = string
  default = "vnet-foundry-speech-interpreter"
}

variable "vnet_cidr" {
  type    = string
  default = "10.74.0.0/24"
}

variable "apps_subnet_cidr" {
  type    = string
  default = "10.74.0.0/27"
}
