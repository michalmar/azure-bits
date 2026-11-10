#!/usr/bin/env bash
set -euo pipefail
export AZURE_CONFIG_DIR="$HOME/.azure-365"
export AZD_CONFIG_DIR="$HOME/.azd-365"
cd "$(dirname "$0")/.."
mkdir -p outputs
log="outputs/live-smoke.log"
# macOS Azure CLI exec needs a TTY. It can return zero even when the remote
# process fails, so check the smoke's explicit completion marker as well.
script -q "$log" az containerapp exec \
  -g rg-foundry-copilot-harness-demo -n foundry-copilot-harness-demo \
  --command 'python /app/app/smoke.py'
grep -q '^LIVE_SMOKE_PASSED' "$log" || {
  printf 'Live smoke did not verify every requirement; inspect %s.\n' "$log" >&2
  exit 1
}
