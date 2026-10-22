# AI Gateway governance Azure infrastructure

Terraform creates a dedicated Sweden Central Container Apps Express environment,
delegated VNet subnet, Basic ACR, user-assigned managed identity, role
assignments, and a scale-to-zero Container App. The existing `demo-swe`
Foundry account (`gpt-6.1-sol`) and `aigw-swe` AI Gateway remain external
inputs and are not recreated.

The app starts locked. `../scripts/deploy.sh` discovers the generated HTTPS
origin, creates or reuses a single-tenant Entra application, stores OAuth,
session, and AI Gateway runtime key secrets in Container Apps, and enables
tenant-wide authenticated access. The workload authenticates to Foundry with
its user-assigned managed identity for the direct baseline, and uses the
Container App secrets (`GATEWAY_APP_KEY`, `GATEWAY_BURST_KEY`) for AI Gateway
runtime calls.

State is local in `infra/terraform.tfstate` and excluded from Git. Restore or
import that state before changing resources if it is lost.
