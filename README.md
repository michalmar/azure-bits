# Azure Bits

Small, focused demos of Azure services and Microsoft Foundry capabilities. Each
demo is self-contained in a top-level folder with its application code,
frontend, tests, infrastructure, and detailed setup instructions.

## Demo directory

| Demo | Description | Frontend | Run and deploy |
| --- | --- | --- | --- |
| [Foundry image models](foundry-image-models/) | Customer-ready gallery and playground for comparing five Foundry image models. Supports prompt-only generation and image editing when the selected model exposes image-input capability. | [Live demo](https://foundry-image-models-demo.calmrock-baf930f6.swedencentral.azurecontainerapps.io) · [Frontend source](foundry-image-models/static/) | [Local setup](foundry-image-models/README.md#local-setup) · [Deploy to Azure](foundry-image-models/README.md#deploy-to-azure) |
| [Azure Speech Live Interpreter](foundry-speech-live-interpreter/) | Browser and CLI demo for real-time speech translation with open-range language detection and synthesized translated audio. | [Frontend source](foundry-speech-live-interpreter/static/) · Local frontend: <http://127.0.0.1:8000> after startup | [Local setup](foundry-speech-live-interpreter/README.md#configure-and-run-locally) · [Infrastructure and deployment](foundry-speech-live-interpreter/README.md#infrastructure) |

The Speech Live Interpreter repository state does not currently record a
deployed Container App, so no public frontend URL is listed.

## Common Azure setup

Azure CLI is expected to be signed in. Set both repository-specific
configuration directories for every Azure CLI, Azure Developer CLI, and
Terraform command:

```bash
export AZURE_CONFIG_DIR="$HOME/.azure-365"
export AZD_CONFIG_DIR="$HOME/.azd-365"
```

Demo workloads use managed identity when accessing Azure services. Do not
replace managed identity with API keys, storage keys, or client secrets.

Before provisioning or deployment, confirm the target subscription, resource
group, dependent Azure resources, expected costs, and authorization to create
resources or role assignments. Follow the linked demo README for the exact
prerequisites and commands.

## Repository conventions

- Keep each demo in its own clearly named top-level folder.
- Keep demo-specific code, configuration, documentation, tests, and Terraform
  inside that folder.
- Include a demo README covering purpose, prerequisites, configuration, local
  execution, validation, and deployment.
- Use the shared [Azure demo frontend skill](.agents/skills/azure-demo-frontend/SKILL.md)
  so browser demos retain consistent typography, colors, controls, navigation,
  spacing, and responsive behavior.
- Use Terraform for Azure infrastructure and Azure Container Apps for deployed
  web demos unless a demo documents an approved exception.
