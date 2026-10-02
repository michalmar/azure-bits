# MAI audio studio

A deliberately small Microsoft Foundry demo for **MAI-Voice-2.1**,
**MAI-Voice-2.1-Flash**, and **MAI-Transcribe-2-Streaming**.

[Open the deployed studio](https://foundry-mai-audio-demo.mangoplant-89bf92cc.swedencentral.azurecontainerapps.io)
using a Microsoft Entra account in the configured tenant.

- **Listen & learn:** source-linked guidance and eight real, cached MAI clips:
  identical support text, expressive delivery, and Harper in Czech and German.
  Each scenario compares both voice models. Replay makes no inference call.
- **Generate speech:** up to 600 characters, curated voice/language and a
  documented style; generate one model or compare both with independent errors.
- **Live captions:** microphone PCM16, automatic language detection, provisional
  suffixes, stable deltas and committed final segments. Stop flushes pending
  audio and waits for finalization. Maximum 60 seconds; commits every 3 seconds.

No LLM, agent framework, browser TTS stand-in, voice cloning, translation engine,
or database is needed. Model information renders without JavaScript. The small
Python backend is needed for managed-identity service calls and reader protection.

## Prerequisites and configuration

Python 3.13+, Node.js for frontend tests, and a modern browser with AudioWorklet.
Microphone capture needs HTTPS or localhost. Live workloads require an Azure host
with a **user-assigned managed identity**; a laptop's Azure CLI login is used only
for administration, not as a workload-authentication fallback.

The deployed demo reuses `demo-swe` / `demo-swe-prj` in Sweden Central. Configure
`FOUNDRY_PROJECT_URL`, or explicitly set `AZURE_MAI_ENDPOINT` to its resource root.
`TRANSCRIBE_DEPLOYMENT` must be an actual deployment of
`MAI-Transcribe-2-Streaming`; voice IDs select the voice models through the Speech
API and do not require separate OpenAI-style deployments.

The workload identity needs **Cognitive Services Speech User** and
**Cognitive Services User** on the existing Foundry account. It has **AcrPull**
on the demo registry and **Storage Blob Data Reader** on only the site container.
No API keys, account keys, or client secrets are used for Azure service access.
The separate Entra credential is solely for reader OAuth login.

Runtime variables:

| Variable | Purpose |
| --- | --- |
| `FOUNDRY_PROJECT_URL` / `AZURE_MAI_ENDPOINT` | Existing Foundry project / resource root |
| `FOUNDRY_ACCOUNT_ID` | Existing account ARM ID; Speech uses the `aad#resource-id#token` Entra bearer format |
| `TRANSCRIBE_DEPLOYMENT` | Streaming model deployment name |
| `AZURE_CLIENT_ID` | User-assigned workload identity client ID |
| `LIVE_AUDIO_ENABLED` | Explicit enablement; false for local/static bootstrap |
| `STORAGE_ACCOUNT_NAME`, `BLOB_CONTAINER_NAME` | Private site content |
| `AUTH_PROVIDER`, `PUBLIC_BASE_URL`, `ALLOWED_USERS` | Reader auth and canonical origin |
| `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET` | Reader-only OAuth configuration |
| `SESSION_SECRET` | Random signed-cookie key, configured as an ACA secret |
| `UPLOAD_API_ENABLED`, `UPLOAD_API_TOKEN_SHA256` | Temporary publisher only; disabled normally |

## Run locally

```bash
cd foundry-mai-audio
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cp .env.example .env
set -a
source .env
set +a
cd app
../.venv/bin/uvicorn app:create_app --factory --host 127.0.0.1 --port 8016 --no-access-log
```

Open `http://127.0.0.1:8016`. This is a **read-only static preview**, with live
buttons disabled and no Azure credential attempt. Cached audio must be generated
and downloaded from the deployed demo if you want offline listening; the checked-in
empty manifest is intentional, never fake audio. Do not set live mode on a laptop
without an available managed-identity endpoint.

## Deploy to Azure

Use the existing Azure CLI login and set these in **each shell invocation**:

```bash
export AZURE_CONFIG_DIR="$HOME/.azure-365"
export AZD_CONFIG_DIR="$HOME/.azd-365"
```

Confirm subscription, dedicated group, role assignments, reader registration and
costs before executing. Terraform creates Container Apps **Express** in Sweden
Central, an ACR, VNet, private Blob endpoint/DNS, Cool storage and user identity.
Storage is network-disabled, shared-key-disabled and non-anonymous from creation.
HTTP scaling is min 0 / max 1. Private networking, ACR, DNS, Cool retention/retrieval
and transfer still cost money at zero replicas.

1. Copy `infra/terraform.tfvars.example` to a private `.tfvars`; point it to the
   existing Foundry account/project. Run `terraform init`, `plan`, then `apply`
   from `infra/` with `container_image=""` to create only the foundation.
2. Build the **code-only** image in the registry with `az acr build`, using
   `https://packagefeedproxy.microsoft.io/pypi/simple` as `PIP_INDEX_URL` in this
   environment. Pin the resulting digest, not a mutable image tag.
3. Set `container_image` to that digest and apply Terraform. The empty anonymous
   bootstrap has live audio and publishing disabled. Its placeholder session
   value does not authorize readers and is replaced before content publication.
4. Save `terraform output -json foundation` to a private `.aca-publish.json`.
   Run `.venv/bin/python scripts/configure_entra.py --settings .aca-publish.json
   --tenant <tenant-guid>` after explicitly approving the reader registration.
   The script uses the actual returned ACA hostname, creates single-tenant reader
   login, allows `tenant:*`, rotates a random session key, enables managed-identity
   audio and stops/starts Express to apply settings. Its reader credential lasts
   180 days; the expiry is recorded in the private settings.
5. Run `pwsh -File scripts/Publish-Content.ps1 -SettingsPath .aca-publish.json
   -Action Upload -Source static -GenerateSamples`. Eight clips are synthesized
   **on Azure using managed identity** and atomically committed individually to
   Cool Blob storage. Versioned clip names and manifest-last publication avoid
   exposing incomplete generation. If generation fails, prior manifest remains.
6. Verify site protection, real login, live synthesis and streaming. Publishing
   disables its relay/digest first and removes the exact temporary Contributor
   assignment in cleanup. Recover interrupted runs with `-Action Lockdown`.

Add `-VerifyStreaming` to a publishing action to synthesize a short, synthetic
PCM phrase with Flash and feed it through the real managed-identity streaming
protocol. It requires a nonempty finalized transcript and reports actual events.
This costs one synthesis and one transcription call. It checks Azure service
access, not interactive Entra login or browser microphone capture. The diagnostic
route is in the ephemeral, bearer-protected publishing namespace and is disabled
with the rest of the relay.
Use `-VerifyGallery` to check all eight audio hashes, MIME/HEAD metadata and
valid/invalid byte ranges through the same Blob reader used by signed-in readers.

The publisher, OAuth, range reader and temporary upload scripts are copied from
the repository's `aca-web-publish` skill. A laptop never opens Storage networking
to upload. `-GenerateSamples` uses the same separately authenticated temporary
publishing namespace; reader sessions cannot publish.

Terraform owns infrastructure. Application `body` is intentionally ignored after
bootstrap because operational ARM updates contain OAuth/session secrets that must
not enter Terraform state. For redeployment, build a new digest and pass `--image`
to `configure_entra.py`; it preserves runtime settings but rotates reader/session
credentials. Retire superseded registration credentials deliberately after a
successful rollout. Directory uploads skip the empty checked-in `samples.json`;
sample generation writes its real manifest last. An explicit `Put` remains
available for intentionally replacing a manifest.

### Deployment evidence

Observed October 2, 2026, on the dedicated `rg-foundry-mai-audio-demo` resources:

- Both voice models generated all eight cached clips on Azure using managed
  identity. All eight downloaded hashes match their provenance manifest.
- The real streaming service transcribed the synthetic phrase
  "This is a short audio model demonstration." exactly, with intermediate,
  delta and completed events. The probe sent 2.542 seconds of PCM; first text
  arrived 321.5 ms after its first backend audio chunk. This single synthetic
  probe is not a word-latency benchmark or a microphone/browser measurement.
- A longer 7.756-second service probe exercised multiple periodic commits.
  User-completed tenant sign-in succeeded in installed, visible Microsoft Edge;
  both live voice models generated browser-decodable MP3s. Authenticated HEAD,
  206 and 416 checks also passed for all eight gallery clips.
- The signed-in Edge caption pipeline processed synthetic demo audio through
  AudioWorklet resampling and the real WebSocket proxy, completed two periodic
  commits, finalized its short tail and exposed transcript download. Real MAI
  boundary probes at 20, 80, 100 and 3,020 ms now finalize successfully while
  reporting the original capture duration.
- Private Blob uploads and reads succeeded while public networking, anonymous
  Blob access and shared keys remained disabled. HEAD, 206 partial reads and
  416 invalid ranges passed for every clip via the protected publishing relay,
  which uses the same Blob reader as the reader-facing routes.
- Express is configured for min 0 / max 1 replica. Idle scale-down was not timed.
  Only container-scoped Blob Data Reader remains; temporary Contributor and
  publishing-token configuration have been removed.
- Anonymous page requests redirect to sign-in, APIs reject unauthenticated
  callers and the microphone WebSocket rejects an anonymous handshake.
  Wrong-origin synthesis requests are rejected even for signed-in readers.
  A separate denied-account login and physical microphone permission/capture
  were not exercised. The synthetic browser probe did not access the user's
  microphone.

The realtime configuration follows the official runnable Python sample: omit
unset language/noise-reduction fields and disable turn detection explicitly.
The documented illustrative `language: null` / `noise_reduction: null` message
was rejected by the deployed preview; the runnable-sample shape succeeded.

## Limits, measurement and privacy

12 calls per reader per minute and 3 concurrent calls across the single process;
these are demo safeguards, not a tenant-wide spend cap. Both-model comparison uses
two calls. Synthesis has a finite timeout and 8 MiB response cap. Microphone input
is bounded by time, total bytes, per-frame bytes and browser send backlog.
The deployed preview requires at least 100 ms per commit. On Stop, a shorter
final tail is padded with silence rather than dropped or rejected. Reported
capture duration excludes that padding; silence adds at most 100 ms of billable
input. This also handles stopping immediately after a periodic commit.
Fixed three-second boundaries can split words; adjacent model-returned segments
may repeat a boundary word. The demo preserves those transcripts rather than
guessing which words to remove. Natural-pause commits would be a separate VAD
integration, deliberately omitted from this minimal demo.

Synthesis reports **Azure request-to-complete audio**, not time to first audio.
The browser round trip is reported separately. Streaming first-text timing starts
when the backend sees the first audio chunk, not when a specific word is spoken.
Launch latency statements are attributed, never presented as locally measured.
Prices are October 2026 list-price estimates, not actual Azure metered charges;
the $0.54/hour transcription promotion ends December 31, 2026.

The application does not persist live text, generated audio, microphone input or
transcripts and disables request access logs. Azure processes submitted input
under the service's own data-handling terms. Downloads are user-controlled.
The intentionally cached gallery contains only synthetic demo text and curated
voices, with model/voice/style, generation duration, timestamp and audio SHA-256
provenance. Voice cloning is omitted: it requires gated access and recorded consent.

## Validation

```bash
PYTHONPATH=app .venv/bin/python -m pytest -q tests
node --test tests/frontend*.test.mjs
terraform -chdir=infra validate
```

Tests cover the reused publisher's auth/ranges/atomic uploads, SSML escaping and
voice/style restrictions, fail-closed local mode, API origin and size limits,
transcription configuration-before-audio and final drain, and exact partial/delta
semantics. Mock service tests are not proof of deployed model access.

## Sources and evidence manifest

Bounded scope: the supplied public launch posts and model cards, plus official
implementation and authentication documentation. No internal or community
material was needed or searched. Reviewed October 2, 2026.

| Source | Date / class | Retrieval and status | Used for |
| --- | --- | --- | --- |
| [Foundry launch](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/build-expressive-voice-experiences-with-new-mai-models-in-microsoft-foundry/4524637) | Oct 1, 2026 / announcement | `web_fetch`, 1 page; text extraction incomplete, HTML JSON-LD supplied full article | Positioning, language coverage, launch pricing, benchmark qualifications |
| [Microsoft AI launch](https://microsoft.ai/news/our-first-streaming-transcription-model/) | Oct 1; updated Oct 2, 2026 / announcement | `web_fetch`, 1 page plus metadata | 26 locales, launch latency examples, pricing |
| [Streaming model card](https://aka.ms/mai-transcribe-2-streaming-foundrycard) | Undated / catalog | `web_fetch`, 1 redirected catalog page; extracted overview only | Partial/final recognition, 60 languages |
| [Voice model card](https://aka.ms/mai-voice-2.1-foundrycard) | Undated / catalog | `web_fetch`, 1 redirected overview; HTML read truncated | Expressive TTS; licensed voices and cloning conditions |
| [Flash model card](https://aka.ms/mai-voice-2.1-flash-foundrycard) | Undated / catalog | `web_fetch`, 1 redirected overview | Low-latency focus; SSML |
| [MAI voice documentation](https://learn.microsoft.com/azure/ai-services/speech-service/mai-voices) | Updated Oct 1, 2026 / documentation | `web_fetch`, overview and voice-table passages, 1 document | Exact voice suffixes, per-voice styles, gated cloning, Sweden availability |
| [Streaming overview](https://learn.microsoft.com/azure/ai-services/speech-service/mai-transcribe-2-streaming) | Updated Oct 1, 2026 / documentation | `web_fetch`, 1 page | API vs SDK integration |
| [Realtime quickstart](https://learn.microsoft.com/azure/ai-services/speech-service/mai-transcribe-2-streaming-realtime) | Updated Oct 1, 2026 / documentation | `web_fetch`, 1 page, protocol passages complete; later sample truncated | Endpoint, Entra, PCM16, delta/intermediate/completed, explicit commits |
| [Speech Entra auth](https://learn.microsoft.com/azure/ai-services/speech-service/how-to-configure-azure-ad-auth) | Updated July 22, 2026 / documentation | `web_fetch`, 1 page, needed setup passages | Token audience and Speech User role |
| [Speech REST reference](https://learn.microsoft.com/azure/ai-services/speech-service/rest-text-to-speech) | Updated June 5, 2026 / documentation | `web_fetch`, authentication passages; remainder truncated | Speech-specific Entra bearer envelope and custom-subdomain endpoint |
| [Non-streaming MAI transcription](https://learn.microsoft.com/azure/ai-services/speech-service/mai-transcribe) | Updated Sept 24, 2026 / documentation | `web_fetch`, 1 page; consulted, not used as streaming contract | Distinguishes batch capabilities from streaming |
| [Express capabilities](https://learn.microsoft.com/azure/container-apps/express-overview) | Updated Sept 23, 2026 / documentation | `web_fetch`, 1 page, required capability passages | Express, user identity, no Easy Auth/custom domain |
| Public API discovery searches | Oct 2, 2026 / discovery | `web_search`, 2 searches, 8 and 2 cited routes respectively | Located official docs; generated summaries not treated as API truth |
| `demo-swe` management state | Oct 2, 2026 / user-authorized Azure observation | Azure CLI, 1 account and project; existing streaming deployment found | Reuse rather than provision a new Foundry account |

Announcements do not independently prove accuracy rankings, production readiness
or universal latency. The official API contract takes precedence over generated
search summaries, which incorrectly suggested automatic turn detection and
streaming diarization. Those claims are not implemented or repeated.
