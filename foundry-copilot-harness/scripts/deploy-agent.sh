#!/usr/bin/env bash
set -euo pipefail
export AZURE_CONFIG_DIR="$HOME/.azure-365"
export AZD_CONFIG_DIR="$HOME/.azd-365"
export AZD_ALPHA_ENABLE_AGENTS_MANAGED_HARNESS=true

cd "$(dirname "$0")/.."
: "${FOUNDRY_PROJECT_URL:?Set the existing Foundry project URL}"
: "${MODEL_DEPLOYMENT_NAME:?Set an existing reasoning/tool-calling deployment}"
AZD_BIN="${AZD_BIN:-azd}"

case "${1:-}" in
  --check|--deploy) ;;
  *) printf 'Usage: %s --check|--deploy\n' "$0" >&2; exit 2 ;;
esac

if [[ "$1" == "--check" ]]; then
  .venv/bin/python scripts/preflight.py
  exit
fi

"$AZD_BIN" env set FOUNDRY_PROJECT_URL "$FOUNDRY_PROJECT_URL"
# The skill extension resolves this name independently of the project service.
"$AZD_BIN" env set FOUNDRY_PROJECT_ENDPOINT "$FOUNDRY_PROJECT_URL"
"$AZD_BIN" env set MODEL_DEPLOYMENT_NAME "$MODEL_DEPLOYMENT_NAME"
"$AZD_BIN" env set AZURE_RESOURCE_GROUP rg-ai
"$AZD_BIN" env set AZURE_AI_PROJECT_NAME demo-swe-prj
"$AZD_BIN" env set AZURE_AI_FOUNDRY_NAME demo-swe
# Prompt agent and skill hosts do not implement azd deploy --preview.
# No azd up/provision: shared infrastructure is never provisioned here.
"$AZD_BIN" deploy --all --no-prompt
"$AZD_BIN" ai agent show workshop-agent --output json
