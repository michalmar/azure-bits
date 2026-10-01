# Flex processing Azure infrastructure

Terraform creates a dedicated Sweden Central Container Apps Express environment,
delegated VNet subnet, Basic ACR, user-assigned managed identity, role
assignments, and a scale-to-zero Container App. The existing `demo-swe`
Foundry account and `gpt-5.6-sol` deployment remain external inputs.

The app starts locked. `../scripts/deploy.sh` discovers the generated HTTPS
origin, creates or reuses a single-tenant Entra application, stores OAuth and
session secrets in Container Apps, and enables tenant-wide authenticated access.
The workload authenticates to Foundry with its user-assigned managed identity.

State is local in `infra/terraform.tfstate` and excluded from Git. Restore or
import that state before changing resources if it is lost.
