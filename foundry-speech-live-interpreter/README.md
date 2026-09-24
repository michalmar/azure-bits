# Azure Speech Live Interpreter

A Python and browser demo for Azure Speech Live Interpreter. The browser streams
16 kHz mono PCM microphone audio over WebSocket, the backend uses open-range
language detection on the universal v2 endpoint, and the page displays interim
and final translations. Synthesized translated audio streams back to the browser
for live playback and is also returned as a WAV when the session stops.

The folder also includes a CLI, focused tests, a container image, and Terraform
for Azure Container Apps Express. Azure access uses Microsoft Entra credentials:
Azure CLI locally and a user-assigned managed identity in Azure. Speech keys are
not supported by this demo.

## Prerequisites

- Python 3.10 or newer.
- Azure CLI signed in through `$HOME/.azure-365`.
- An existing Speech resource in a Live Interpreter supported region.
- Live Interpreter approval on that exact resource.
- **Cognitive Services Speech User** for the local user or deployed identity.
- Personal Voice approval on the same resource before enabling that option.

## Configure and run locally

```bash
cd foundry-speech-live-interpreter
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Set `AZURE_SPEECH_RESOURCE_NAME`, tenant/subscription values, and the required
Azure CLI profile in `.env`, then export them before starting the server:

```bash
set -a
source .env
set +a
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`, allow microphone access, choose the target
language, and select **Start interpreting**. Headphones prevent synthesized
speech from feeding back into the microphone.

The browser requires a secure context for microphone access. `localhost` is
accepted locally; Azure uses HTTPS automatically.

## Run the CLI

```bash
python cli.py --target-language fr
python cli.py --target-language de --voice de-DE-KatjaNeural --wav input.wav
python cli.py --target-language fr --voice personal-voice
```

Use `Ctrl+C` to stop microphone input. The CLI writes translated audio to
`translated.wav` by default.

## Test

```bash
python -m pytest -q
```

## Infrastructure

Terraform in `infra/` creates:

- a dedicated resource group in Sweden Central;
- a delegated VNet subnet and Container Apps **Express** environment;
- a Basic ACR with admin access disabled;
- a user-assigned managed identity;
- `AcrPull`, `Cognitive Services Speech User`, and optional Key Vault secret
  reader assignments;
- a dedicated RBAC-enabled Key Vault for the Entra client secret and signed
  session secret;
- a public HTTPS Container App with min 0 / max 1 replicas.

The first apply can create only the foundation. The Container App is created
after an immutable image is provided, initially with authentication disabled.
The deployment then performs an in-memory ARM update that stores the OAuth and
session values as encrypted Container Apps secrets and enables authentication.
Plaintext values do not enter source files, command arguments, or Terraform
state. A dedicated Key Vault is still provisioned for environments whose policy
allows private-endpoint secret injection.

Before any apply or deployment, confirm the target subscription, dedicated
resource group, Speech resource, Key Vault, Entra application, reader allowlist,
and authorization to create resources and role assignments. Azure costs remain
for ACR, Express infrastructure, networking, and Key Vault even when the app
scales to zero.

All Azure and Terraform commands must use:

```bash
export AZURE_CONFIG_DIR="$HOME/.azure-365"
export AZD_CONFIG_DIR="$HOME/.azd-365"
```

Example validation:

```bash
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false -input=false
terraform -chdir=infra validate
```

Do not enable `personal_voice_enabled` until limited-access approval is verified
on the exact configured Speech resource.

Reader authorization accepts `tenant:*` for every authenticated user in the
configured tenant, or explicit `entra:<object-id>` / `email:<address>` entries.
