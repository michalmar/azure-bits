# Infrastructure

Terraform in this directory provisions the Azure resources for the Foundry image
models demo:

- a dedicated resource group in `swedencentral`
- a VNet with a delegated Azure Container Apps subnet
- a Basic Azure Container Registry with admin access disabled
- a user-assigned managed identity
- `Reader` and `Cognitive Services User` role assignments on the
  existing Foundry account
- an Azure Container Apps Express managed environment via the `azapi` provider
- a public Container App using the UAMI for runtime and image pulls

The deployment flow is intentionally staged:

1. apply the foundation without an app image on first deployment, or preserve
   the existing Container App unchanged while applying other infrastructure on
   updates
2. build the container image in ACR and apply the app with the immutable digest
   on first deployment
3. run `scripts/configure_entra.py` once the live HTTPS origin is known; on
   updates this changes the image digest and authentication atomically

Use `scripts/deploy.sh` for updates rather than stopping after a standalone
Terraform apply. Terraform creates the Container App bootstrap only on the first
deployment; subsequent foundation plans explicitly exclude that application.
After a successful build, `configure_entra.py` hydrates the current secret values
through `listSecrets`, changes the image and authentication in one conditional
ARM update, and restores the previous snapshot if any later step fails.
Plaintext credentials never enter Terraform state, and the configuration step
remains the final application update.

## Terraform state recovery

This demo currently uses local Terraform state in `infra/terraform.tfstate`.
Keep that file in the authorized deployment workspace or back it up through
your organization's approved secure process. It is intentionally excluded from
Git because state can contain sensitive infrastructure metadata.

The deploy script fails closed when the target resource group or Container App
exists without matching local state. If state is lost:

1. restore the original `infra/terraform.tfstate` backup, or
2. import the existing resources into a fresh state after reviewing every
   resource address and Azure ID, then run `terraform plan` and require a
   non-destructive result before deployment.

Do not bypass the guard or apply with an empty state against the existing
resource group.

## Local checks

From the repository root:

```bash
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -input=false
terraform -chdir=infra validate
python -m py_compile scripts/configure_entra.py
bash -n scripts/deploy.sh
pytest tests/infra -q
```

## Deployment notes

- The deploy script verifies the target subscription before any Azure action.
- Azure CLI and Terraform commands always run with `AZURE_CONFIG_DIR=$HOME/.azure-365`
  and `AZD_CONFIG_DIR=$HOME/.azd-365`.
- `configure_entra.py` keeps secrets in memory and updates the Container App
  through ARM and Microsoft Graph calls; it does not write plaintext secrets to
  Terraform state, shell history, or files.
- The deployed app is configured for a single Entra tenant and all authenticated
  users in that tenant; per-user allowlisting is intentionally not part of the
  infrastructure. Live allow-vs-denied verification requires separate user
  accounts and is not automated here.
