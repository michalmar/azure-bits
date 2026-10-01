# GPT-5.6 Sol Flex processing comparison

A reproducible Microsoft Foundry demo that sends the same arbitrary prompt to
the existing `gpt-5.6-sol` deployment twice and starts both requests together:

- **Standard processing** with `service_tier: "default"`;
- **Flex processing** with `service_tier: "flex"`.

**Live demo:** [Open the GPT-5.6 Sol processing comparison](https://foundry-flex-demo.mangoplant-8b221bda.swedencentral.azurecontainerapps.io).
Sign in with an account in the configured Entra tenant.

The frontend presents both full responses side by side and compares
authentication time, request-to-headers time, headers-to-first-text-token time,
generation time, total latency, token consumption, and estimated token cost.
The separate **Test results** tab reads `static/results.json` and presents a
checked-in ten-run benchmark with aggregate median/p95 statistics and expandable
individual runs.

Flex processing is a request-level choice on the same Global Standard
deployment. It uses the same underlying model but has no latency or availability
SLA, can return capacity-related HTTP 429 responses, and is billed at a 50%
discount from the corresponding Standard token rates. See the official
[Flex processing guide](https://learn.microsoft.com/azure/foundry/openai/how-to/flex-processing).

## Prerequisites

- Python 3.12 or later and Node.js 20 or later.
- Azure CLI signed in under `$HOME/.azure-365`.
- **Cognitive Services OpenAI User** access to the existing Azure OpenAI
  resource.
- A `gpt-5.6-sol` version `2026-07-09` Global Standard deployment. The default
  configuration uses deployment `gpt-5.6-sol` on
  `https://demo-swe.openai.azure.com`.

The backend uses `AzureCliCredential` locally and a user-assigned
`ManagedIdentityCredential` when `APP_ENV=production`. No API key or Azure
credential is sent to the browser.

## Run locally

```bash
export AZURE_CONFIG_DIR="$HOME/.azure-365"
export AZD_CONFIG_DIR="$HOME/.azd-365"

cd foundry-flex-processing
python3.12 -m venv .venv
.venv/bin/python -m pip install \
  --index-url https://packagefeedproxy.microsoft.io/pypi/simple \
  -r requirements.txt
cp .env.example .env
set -a
source .env
set +a
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. Each comparison run creates two billable model
requests. The requests are concurrent, so the reported page wall-clock time is
approximately the slower request rather than the sum of both requests.

## Pricing and cost calculation

At startup, the backend reads the four GPT-5.6 Sol Global short-context Standard
meters from the public [Azure Retail Prices API](https://prices.azure.com/api/retail/prices):

| Usage category | Retail meter SKU |
| --- | --- |
| Regular input | `5.6 sol ShortCo Inp Std Gl` |
| Cached input | `5.6 sol ShortCo Cd Inp Std Gl` |
| Cache write | `5.6 sol ShortCo Cd Wr Std Gl` |
| Output | `5.6 sol ShortCo Opt Std Gl` |

Flex rates are derived by multiplying each Standard rate by `0.5`, as documented
by Microsoft. The pricing response, meter names, retrieval timestamp, currency,
and any fallback warning are returned to the frontend with every run.

If the Retail Prices API is unavailable or returns ambiguous meter data, the
backend logs the failure and visibly falls back to the pricing snapshot captured
on **2026-09-29**: Standard `$4.00` input, `$0.40` cached input, `$5.00` cache
write, and `$20.00` output per one million tokens. Verify current rates on the
[Azure OpenAI pricing page](https://azure.microsoft.com/pricing/details/azure-openai/)
before making purchasing decisions.

The estimated request cost is:

```text
regular input tokens × input rate
+ cached input tokens × cached-input rate
+ cache-write tokens × cache-write rate
+ output tokens × output rate
```

Each component is divided by one million. The response's actual processed
`service_tier` selects Standard or Flex rates, rather than assuming the requested
tier was honored.

## Measurement method

The FastAPI backend streams both Responses API calls and records timestamps with
Python's monotonic `perf_counter()`:

1. Entra access-token acquisition.
2. HTTP request start to response headers.
3. Response headers to the first `response.output_text.delta`.
4. First text token to `response.completed`.
5. Total elapsed time.

This is an application-observed measurement, not server telemetry. DNS, TLS,
connection-pool reuse, client location, shared deployment quota, prompt caching,
model reasoning, and temporary Flex capacity can all affect a run. For a useful
benchmark, repeat a fixed prompt many times at representative hours and compare
distributions such as median and p95. Do not infer an SLA from one comparison.

## Validate

```bash
export AZURE_CONFIG_DIR="$HOME/.azure-365"
export AZD_CONFIG_DIR="$HOME/.azd-365"

cd foundry-flex-processing
.venv/bin/python -m pytest -q
node --test tests/frontend.test.mjs
```

The automated tests do not call the model. A real end-to-end validation is
performed only when you select **Run parallel comparison**, and it consumes
tokens on the configured deployment.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `AZURE_OPENAI_ENDPOINT` | `https://demo-swe.openai.azure.com` | Azure OpenAI resource origin. |
| `AZURE_OPENAI_DEPLOYMENT` | `gpt-5.6-sol` | Existing Global Standard deployment name. |
| `FLEX_REQUEST_TIMEOUT_SECONDS` | `900` | Client timeout; Flex can take substantially longer than Standard. |
| `DEFAULT_MAX_OUTPUT_TOKENS` | `800` | Initial output limit shown in the frontend. |
| `PRICING_CURRENCY` | `USD` | Retail Prices API currency code. |
| `MAX_TRANSIENT_ATTEMPTS` | `3` | Bounded attempts for HTTP 408, 429, 500, 502, 503, and 504 responses. |
| `APP_ENV` | `development` | Set to `production` to use managed identity. |
| `AZURE_CLIENT_ID` | unset | User-assigned managed identity client ID in production. |

Terraform in `infra/` deploys the application to a dedicated Container Apps
Express environment in Sweden Central. It creates a Basic ACR, delegated VNet
subnet, user-assigned managed identity, role assignments, and a scale-to-zero
Container App with one maximum replica. The existing Foundry deployment remains
external and is never recreated.

The deployed site uses single-tenant Entra login and permits authenticated users
from the configured tenant. The workload identity receives `AcrPull` on its
registry and `Cognitive Services OpenAI User` on the existing Foundry account.

## Deploy to Azure

Confirm the subscription, dedicated resource group, tenant-wide reader access,
resource costs, and role-assignment authorization before applying. Then run:

```bash
export AZURE_CONFIG_DIR="$HOME/.azure-365"
export AZD_CONFIG_DIR="$HOME/.azd-365"
export AZURE_SUBSCRIPTION_ID="<approved-subscription-id>"
export ENTRA_TENANT_ID="<approved-tenant-id>"
./scripts/deploy.sh
```

The script verifies the existing `gpt-5.6-sol` deployment, provisions Terraform,
builds an immutable image in ACR, discovers the generated HTTPS hostname,
creates or reuses a single-tenant Entra application, stores secrets in Container
Apps, and verifies Express mode, managed identity, scaling, health, and the
unauthenticated login redirect.

## Refresh the static ten-run result set

Start the application locally, then run:

```bash
.venv/bin/python scripts/run_benchmark.py \
  --base-url http://127.0.0.1:8877 \
  --runs 10 \
  --max-output-tokens 400
```

The script sends ten sequential comparison jobs. Each job starts Standard and
Flex together, so refreshing the dataset creates **20 billable requests**. It
writes raw responses, latency phases, token usage, costs, retries, timestamps,
and aggregate median/p95 values to `static/results.json`.

Transient HTTP 408, 429, 500, 502, 503, and 504 responses are retried with
bounded exponential backoff, jitter, and `Retry-After` support. A Flex request
is never silently replaced with Standard because that would invalidate the
comparison.
