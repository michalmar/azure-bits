# Repository guidance

## Purpose and structure

This repository contains demos of Azure services and AI features.

- Keep each demo in its own clearly named top-level folder.
- Keep demo-specific code, configuration, documentation, and infrastructure
  within that demo's folder.
- Include a README for each demo with its purpose, prerequisites, configuration,
  and local run instructions.

## Technology choices

- Use Python for demos that need a backend, with a simple frontend.
- Frontend-only demos are also supported; do not add a backend unnecessarily.
- Keep implementations focused and easy to understand.

## Azure environment

Azure CLI is available and already signed in. Use the existing login and set
both environment variables for all Azure-related commands, including Azure CLI,
Azure Developer CLI, and Terraform:

```sh
export AZURE_CONFIG_DIR="$HOME/.azure-365"
export AZD_CONFIG_DIR="$HOME/.azd-365"
```

Ensure these variables are set in each shell invocation; do not assume they
persist between tool calls.

Unless explicitly instructed otherwise, use the Microsoft Foundry project
configured in the local environment:

```text
FOUNDRY_PROJECT_URL
```

## Authentication

- Always use managed identity for demo workloads accessing Azure services,
  including Foundry. Do not use API keys, storage account keys, or client secrets
  as a substitute.
- Use the existing Azure CLI session for local administrative and provisioning
  commands; this does not replace the workload's managed identity.
- If managed identity is unavailable in the intended execution environment,
  explain the limitation and ask for direction rather than silently switching
  authentication methods.
- Never put credentials in source code or frontend assets. A frontend-only demo
  must not attempt to expose or use a managed identity directly in the browser;
  use an identity-enabled backend if Azure service access requires one.

## Infrastructure and deployment

- Whenever creating a new demo, ask the user whether to create infrastructure
  for it. Do not assume that a new demo authorizes resource creation.
- Use Terraform whenever infrastructure is needed.
- If deployment is needed, deploy to Azure Container Apps and follow the
  repository's [aca-web-publish skill](.agents/skills/aca-web-publish/SKILL.md).
- The Terraform requirement also applies when following that skill: translate
  its bundled Bicep infrastructure examples into Terraform while preserving
  the skill's deployment and security requirements.
- Confirm the target subscription, resource group, and authorization before
  provisioning resources or deploying.

## Frontend consistency

- Every demo frontend must share the same look and feel.
- Reuse existing frontend styles, design tokens, components, and layout patterns
  instead of creating a separate visual design for each demo.
- Keep typography, colors, spacing, navigation, buttons, forms, and interaction
  patterns consistent across demos.
- If no frontend baseline exists yet, establish a simple reusable baseline with
  the first frontend and use it for subsequent demos.
