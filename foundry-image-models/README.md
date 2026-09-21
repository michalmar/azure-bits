# Foundry image models demo

A customer-ready comparison gallery and interactive playground for five image
deployments in Microsoft Foundry:

- `gpt-image-2.5-sunburst`
- `MAI-Image-2.6-Flash`
- `MAI-Image-2.6`
- `MAI-Image-2.5`
- `gpt-image-2`

The gallery contains three fixed prompts and one generated result from every model.
The playground supports prompt-only generation and image-plus-prompt editing when the
model capability API reports `imageEdits: true`.

## Architecture

- **Frontend:** dependency-free HTML, CSS, and JavaScript.
- **Backend:** FastAPI with direct MAI and Azure OpenAI image REST calls.
- **Authentication:** Azure CLI locally; user-assigned managed identity in Azure.
- **Reader access:** single-tenant Entra OIDC for all authenticated users in the
  configured tenant.
- **Hosting:** Azure Container Apps Express, min 0 and max 1 replica.
- **Infrastructure:** Terraform with `azurerm` and `azapi`.
- **Storage:** none. Playground uploads and generated images stay in browser or process
  memory only. Starting a new browser session discards the current work.

The pre-generated gallery images are static demonstration assets in
`static/gallery/`. User playground images are never written to disk or durable Azure
storage.

## Prerequisites

- Python 3.11 or later
- Azure CLI signed in to the intended deployment subscription
- Terraform 1.7 or later for deployment
- Access to the existing `demo-swe` Foundry resource and its deployed models

Set the repository-required Azure configuration directories for every Azure command:

```bash
export AZURE_CONFIG_DIR="$HOME/.azure-365"
export AZD_CONFIG_DIR="$HOME/.azd-365"
```

## Local setup

```bash
cd foundry-image-models
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`requirements.in` contains the direct dependency ranges. Regenerate the hashed
Python 3.12 Linux lock through the approved package feed when dependencies
change:

```bash
uv --config-file /dev/null pip compile requirements.in \
  --python-version 3.12 \
  --python-platform x86_64-unknown-linux-gnu \
  --index-url https://packagefeedproxy.microsoft.io/pypi/simple \
  --generate-hashes \
  --output-file requirements.txt
```

Local development uses `AzureCliCredential` and has reader authentication disabled by
default:

```bash
export AZURE_CONFIG_DIR="$HOME/.azure-365"
export AZD_CONFIG_DIR="$HOME/.azd-365"
export FOUNDRY_SUBSCRIPTION_ID="<subscription-id>"
export FOUNDRY_RESOURCE_GROUP="<foundry-resource-group>"
export FOUNDRY_ACCOUNT_NAME="<foundry-account-name>"
export FOUNDRY_BASE_URL="https://<foundry-account>.services.ai.azure.com"
export FOUNDRY_PROJECT_URL="$FOUNDRY_BASE_URL/api/projects/<project-name>"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>.

## Generate or refresh the gallery

The generator uses model defaults: it does not send size, quality, output format, or
other optional generation settings.

```bash
export AZURE_CONFIG_DIR="$HOME/.azure-365"
export AZD_CONFIG_DIR="$HOME/.azd-365"
.venv/bin/python scripts/generate_gallery.py --concurrency 2
```

Generation is resumable. Successful images are checkpointed after each result, and a
partial run exits nonzero while preserving completed work. Use `--force` to regenerate
existing successful images.

Image generation can take several minutes. Override the five-minute upstream timeout
only when needed:

```bash
export FOUNDRY_UPSTREAM_TIMEOUT_SECONDS=420
```

## Validation

```bash
.venv/bin/python -m pytest tests/backend -q
node --test tests/frontend/app.test.js

terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -input=false
terraform -chdir=infra validate
python3 -m unittest discover -s tests/infra -q
```

## Deploy to Azure

Supply deployment-specific identifiers through the environment so they are not
committed to the repository:

```bash
export AZURE_SUBSCRIPTION_ID="<deployment-subscription-id>"
export ENTRA_TENANT_ID="<allowed-tenant-id>"
export FOUNDRY_SUBSCRIPTION_ID="$AZURE_SUBSCRIPTION_ID"
export FOUNDRY_RESOURCE_GROUP="<foundry-resource-group>"
export FOUNDRY_ACCOUNT_NAME="<foundry-account-name>"
export FOUNDRY_BASE_URL="https://<foundry-account>.services.ai.azure.com"
```

The script deploys the demo resource group in Sweden Central and derives the
Foundry role-assignment scope from these values.

Deploy from the demo directory:

```bash
export AZURE_CONFIG_DIR="$HOME/.azure-365"
export AZD_CONFIG_DIR="$HOME/.azd-365"
./scripts/deploy.sh
```

The script:

1. verifies the subscription and required providers;
2. provisions the Terraform foundation;
3. builds the container in ACR;
4. deploys the immutable image digest to Container Apps Express;
5. creates or reuses a tenant-only Entra application registration;
6. configures the live callback URL and in-memory-generated credentials;
7. verifies Express mode, identity bindings, scale settings, health, and the
   unauthenticated login redirect.

On updates, Terraform applies only the resources outside the existing Container App, so
the foundation phase cannot strip working authentication while ACR builds the replacement
image. After the build succeeds, the Entra configurator updates the immutable image digest
and authentication together in one conditional ARM update. Existing secret values are
read through `listSecrets`, kept only in process memory, and restored automatically if the
update fails. The Entra client credential is never written to source, Terraform state,
command-line arguments, settings files, or logs. The deployment output includes its
expiration date. Use `scripts/configure_entra.py --rotate-client-secret` during a controlled
maintenance run to rotate it.

Container Apps Express is a preview service. Scale-to-zero reduces application compute
when idle, but ACR and any other retained Azure resources can still incur charges.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `development` | Uses managed identity only when set to `production`. |
| `AZURE_CLIENT_ID` | none | User-assigned managed identity client ID in Azure. |
| `FOUNDRY_BASE_URL` | required for real calls | Image API base URL. |
| `FOUNDRY_SUBSCRIPTION_ID` | required for real calls | Capability API lookup. |
| `FOUNDRY_RESOURCE_GROUP` | required for real calls | Capability API lookup. |
| `FOUNDRY_ACCOUNT_NAME` | required for real calls | Capability API lookup. |
| `FOUNDRY_UPSTREAM_TIMEOUT_SECONDS` | `300` | Image API timeout. |
| `FOUNDRY_MAX_PROMPT_LENGTH` | `4000` | Prompt validation limit. |
| `FOUNDRY_MAX_IMAGE_BYTES` | `900000` | Upload validation limit. |
| `AUTH_ENABLED` | `false` | Enables tenant-specific Entra OIDC when `true`. |
| `PUBLIC_BASE_URL` | none | Live Container Apps HTTPS origin. |
| `ENTRA_TENANT_ID` | none | Allowed Entra tenant. |
| `ENTRA_CLIENT_ID` | none | OIDC application client ID. |
| `ENTRA_CLIENT_SECRET` | none | OIDC application secret, supplied as an ACA secret. |
| `SESSION_SECRET` | none | Signs the minimal application session cookie. |
