# GPT-Live conversation demo

A small browser demo of [`gpt-live-1`](https://learn.microsoft.com/azure/foundry/openai/concepts/gpt-live):
talk to the model, speak again while it is answering, and watch the two transcript
streams interleave. The [Foundry multimodal announcement](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/create-multimodal-applications-with-openai-models-in-microsoft-foundry/4543593)
describes this full-duplex interaction alongside GPT-Image-2.5; the separate
[image models demo](../foundry-image-models/) covers image generation. GPT-Live
itself produces voice, not generated images.

**Live demo:** [Open the GPT-Live conversation](https://foundry-gpt-live-demo.wonderfulforest-c2bd4c50.swedencentral.azurecontainerapps.io).
Sign in with an account in the configured Entra tenant.

The page shows microphone and model audio activity, the live transcript, a mute
control, and a **configurable countdown**. Choose **1 to 15 minutes** in one-minute
steps with the minus and plus buttons; the default is **5 minutes**. Conversations
stop on the server after the selected duration, even if the tab is left open.
The demo accepts at most three live
connections per app process. No tools, external actions, or durable conversation
storage are connected; if GPT-Live delegates work, the backend tells it that
the requested action is unavailable.

## Conversation duration

Set **Conversation duration** before selecting **Start conversation**. The
buttons are locked while connecting, talking, and ending the conversation.
The chosen value stays selected for the next conversation in this tab; a page
reload restores the five-minute default. Longer conversations incur more
model-session charges, including time spent silent.

The backend validates the selected duration before opening a metered model
connection, enforces it independently of the browser countdown, and never accepts
more than 15 minutes or non-whole-minute durations. `MAX_SESSION_SECONDS` is the
server ceiling, not the default selection; it defaults to 900. Operators can
lower it in whole-minute steps, in which case the initial selection is the smaller
of five minutes and that ceiling.

## System prompt

The **System prompt** editor starts with the demo's existing **Default**
instructions. Choose **Language tutor** or **Grill** to replace the
editor text with a ready-made prompt, or edit the text to provide your own
instructions. **Default** restores the original prompt. All three presets remain
editable; a custom prompt replaces, rather than appends to, the default.
Grill guides a spoken discussion of plans and decisions, one question at a time.
It does not add file access, lookups, or external tools to the demo.

The prompt is sent when you select **Start conversation** and stays fixed for
that conversation. End the conversation to edit it for the next one. A prompt
must contain non-whitespace text and be at most 12,000 characters. Custom text
stays in this tab across conversations, but is not saved across page reloads
or stored by the server.

Preset labels and text are defined in `PROMPT_PRESETS` in
[`app/live.py`](app/live.py); `INSTRUCTIONS` is the default and
`GRILL_INSTRUCTIONS` holds the full Grill prompt. The authenticated
`/api/config` response supplies the presets and length limit to the frontend.
The browser's first WebSocket message is
`{"type":"start","instructions":"...","durationSeconds":300}`. Omitting
`durationSeconds` uses the default duration for older clients.
The server validates it before opening
a metered model connection and uses the supplied text as `session.instructions`
in `session.start`. Clients must send that message within 15 seconds; subsequent
messages are audio, mute, or stop commands, not prompt updates.

Frontend assets use content-versioned URLs, including JavaScript module imports
and the audio worklet, so a browser with a previous release cached cannot mix
old code with the new page. HTML and configuration responses are not stored in
the browser cache. If configuration fails or takes more than 15 seconds, the
page shows an explicit error instead of remaining on "Loading prompt presets".

## How it works

- The browser captures microphone audio with an `AudioWorklet`, resamples it to
  **24 kHz mono PCM16**, and streams frames over a same-origin WebSocket. It plays
  the streamed PCM response and displays timed input/output transcript fragments.
- The FastAPI backend opens
  `/openai/v1/live/sessions` on the **existing** `demo-swe` Foundry account,
  starts the `gpt-live-1` deployment, and closes the upstream session when the
  user stops, disconnects, or reaches the selected time limit.
- Only the backend authenticates to Azure: `AzureCliCredential` locally and a
  **user-assigned managed identity** in Container Apps. No Azure credential is
  sent to the browser. The deployed site uses a single-tenant Entra login and
  explicitly allows authenticated users in the configured tenant.
- Audio and transcripts are processed in memory. No Blob account, database,
  upload API, or browser persistence is used.

The [GPT-Live WebSocket guide](https://learn.microsoft.com/azure/foundry/openai/how-to/gpt-live)
and [event reference](https://learn.microsoft.com/azure/foundry/openai/gpt-live-reference)
describe the protocol. WebRTC can lower latency for production browser
applications, but requires backend session negotiation and lifecycle handling;
this small demo keeps the entire session under one bounded, authenticated
WebSocket.

## Prerequisites

- Python 3.12 or later, Node.js for frontend tests, and a modern browser with
  microphone and AudioWorklet support.
- Azure CLI signed in under `$HOME/.azure-365` with **Cognitive Services OpenAI
  User** on `demo-swe` in `rg-ai`.
- The existing `gpt-live-1` deployment on that account. No model deployment is
  created by this demo.
- For Azure deployment: Terraform 1.8+, permission to create a resource group,
  Container Apps Express environment, Basic ACR, VNet, user-assigned identity,
  role assignments, and a single-tenant Entra app registration.

## Run locally

```bash
cd foundry-gpt-live
python3.12 -m venv .venv
.venv/bin/python -m pip install --index-url https://packagefeedproxy.microsoft.io/pypi/simple -r requirements.in
cp .env.example .env
set -a
source .env
set +a
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>, choose **Start conversation**, and allow the
microphone. `localhost` and `127.0.0.1` are secure contexts for microphone
access; a remote deployment needs HTTPS. Headphones help avoid echo.

Set `AZURE_OPENAI_ENDPOINT` to the HTTPS **OpenAI account origin**, not a Foundry
project URL; for this demo it is `https://demo-swe.openai.azure.com`. Set
`LIVE_DEPLOYMENT` if the existing deployment is named differently.
`MAX_SESSION_SECONDS` defaults to 900 and accepts whole-minute values from 60
to 900; use 900 for the full 1-15 minute selector. The deployment script applies
this ceiling to existing apps as well as new deployments.
The checked-in `requirements.txt` is a hashed **Linux/Python 3.12**
container lock; local macOS development installs from `requirements.in` through
the approved feed.

## Check locally

```bash
.venv/bin/python -m pytest tests/test_live.py -q
node --test tests/frontend.test.mjs
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false -input=false
terraform -chdir=infra validate
```

The test suite uses an in-memory fake GPT-Live connection and never bills the
model. Testing the real microphone and live voice requires signing in and
starting a conversation in a browser.

## Deploy to Azure

Terraform in [`infra/`](infra/README.md) provisions a dedicated resource group
in Sweden Central, a delegated VNet subnet, an Express environment, Basic ACR,
a user-assigned identity, and a public HTTPS Container App with HTTP scaling
from **zero to at most one** replica. The app identity receives `AcrPull` and
`Cognitive Services OpenAI User` on the existing Foundry account. The app stays
**locked** until the live HTTPS hostname is known and single-tenant Entra OIDC
is configured. OAuth and session secrets are kept out of source, shell arguments,
and Terraform state.

Confirm the subscription, resource group, allowed readers, costs, and
authorization before applying. Then, with the intended Azure CLI profile:

```bash
export AZURE_CONFIG_DIR="$HOME/.azure-365"
export AZD_CONFIG_DIR="$HOME/.azd-365"
export AZURE_SUBSCRIPTION_ID="<approved-subscription-id>"
export ENTRA_TENANT_ID="<approved-tenant-id>"
./scripts/deploy.sh
```

The script defaults to the existing `demo-swe` account in `rg-ai`. Set
`FOUNDRY_ACCOUNT_NAME`, `FOUNDRY_RESOURCE_GROUP`, and
`AZURE_OPENAI_ENDPOINT` together if you are using a different already
deployed account. It checks the live `gpt-live-1` deployment before
provisioning and fails if the target resource group exists without this
checkout's Terraform state. On repeat runs it preserves the active app while
building a new image and updates its image through the auth configurator,
not an unguarded Terraform replacement.

The deployment can incur ongoing **ACR, VNet/Express, and model-session charges**
even when replicas scale to zero. The tenant-wide allowlist permits any
authenticated user in the selected Entra tenant to start a metered session.
Express is a preview service; a successful Terraform apply is not proof that
`environmentMode` is Express, so the script checks the live resource.
