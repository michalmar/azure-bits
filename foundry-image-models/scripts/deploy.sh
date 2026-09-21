#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_DIR="$ROOT_DIR/infra"
BUILD_CONTEXT="$ROOT_DIR/.deploy-build-context"
TARGET_SUBSCRIPTION="${AZURE_SUBSCRIPTION_ID:?Set AZURE_SUBSCRIPTION_ID to the deployment subscription UUID}"
TARGET_TENANT_ID="${ENTRA_TENANT_ID:?Set ENTRA_TENANT_ID to the allowed Entra tenant UUID}"
TARGET_RESOURCE_GROUP="rg-foundry-image-models-demo"
TARGET_LOCATION="swedencentral"
FOUNDRY_SUBSCRIPTION_ID="${FOUNDRY_SUBSCRIPTION_ID:-$TARGET_SUBSCRIPTION}"
FOUNDRY_RESOURCE_GROUP="${FOUNDRY_RESOURCE_GROUP:?Set FOUNDRY_RESOURCE_GROUP to the existing Foundry resource group}"
FOUNDRY_ACCOUNT_NAME="${FOUNDRY_ACCOUNT_NAME:?Set FOUNDRY_ACCOUNT_NAME to the existing Foundry account name}"
FOUNDRY_BASE_URL="${FOUNDRY_BASE_URL:?Set FOUNDRY_BASE_URL to the Foundry account base URL}"
FOUNDRY_ACCOUNT_SCOPE_ID="/subscriptions/$FOUNDRY_SUBSCRIPTION_ID/resourceGroups/$FOUNDRY_RESOURCE_GROUP/providers/Microsoft.CognitiveServices/accounts/$FOUNDRY_ACCOUNT_NAME"
TF_COMMON_VARS=(
  "-var=subscription_id=$TARGET_SUBSCRIPTION"
  "-var=location=$TARGET_LOCATION"
  "-var=resource_group_name=$TARGET_RESOURCE_GROUP"
  "-var=foundry_account_scope_id=$FOUNDRY_ACCOUNT_SCOPE_ID"
  "-var=foundry_subscription_id=$FOUNDRY_SUBSCRIPTION_ID"
  "-var=foundry_resource_group=$FOUNDRY_RESOURCE_GROUP"
  "-var=foundry_account_name=$FOUNDRY_ACCOUNT_NAME"
  "-var=foundry_base_url=$FOUNDRY_BASE_URL"
  "-var=azure_ai_endpoint=$FOUNDRY_BASE_URL"
  "-var=entra_tenant_id=$TARGET_TENANT_ID"
)
IMAGE_REPO="foundry-image-models-demo"
IMAGE_TAG="deploy-$(date -u +%Y%m%d%H%M%S)"
PLAN_FILE="$INFRA_DIR/deploy.tfplan"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
CURRENT_PUBLIC_BASE_URL=""
CURRENT_ENTRA_CLIENT_ID=""
CURRENT_ENTRA_CLIENT_SECRET_NAME=""
CURRENT_SESSION_SECRET_NAME=""
CONTAINER_APP_EXISTS=false
BUILT_IMAGE=""

export AZURE_CONFIG_DIR="${AZURE_CONFIG_DIR:-$HOME/.azure-365}"
export AZD_CONFIG_DIR="${AZD_CONFIG_DIR:-$HOME/.azd-365}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

az_wrap() {
  AZURE_CONFIG_DIR="$AZURE_CONFIG_DIR" AZD_CONFIG_DIR="$AZD_CONFIG_DIR" az "$@"
}

tf_wrap() {
  AZURE_CONFIG_DIR="$AZURE_CONFIG_DIR" AZD_CONFIG_DIR="$AZD_CONFIG_DIR" terraform -chdir="$INFRA_DIR" "$@"
}

container_app_fqdn() {
  local app_id
  app_id="$(tf_wrap output -raw container_app_id)"
  az_wrap rest --method get \
    --url "https://management.azure.com${app_id}?api-version=2026-03-02-preview" \
    --query "properties.configuration.ingress.fqdn" -o tsv
}

current_container_image() {
  local state_resources app_id image
  state_resources="$(tf_wrap state list)"
  if ! grep -Fqx "azapi_resource.container_app[0]" <<<"$state_resources"; then
    return 0
  fi
  CONTAINER_APP_EXISTS=true

  if ! app_id="$(tf_wrap output -raw container_app_id)" || [[ -z "$app_id" ]]; then
    echo "Container App exists in Terraform state, but its resource ID could not be read." >&2
    return 1
  fi
  if ! image="$(az_wrap rest --method get \
    --url "https://management.azure.com${app_id}?api-version=2026-03-02-preview" \
    --query "properties.template.containers[0].image" -o tsv)"; then
    echo "Container App image lookup failed; refusing a plan that could destroy the running app." >&2
    return 1
  fi
  if [[ ! "$image" =~ @sha256:[0-9a-f]{64}$ ]]; then
    echo "Container App image is missing an immutable digest; refusing to continue." >&2
    return 1
  fi
  printf '%s\n' "$image"
}

verify_local_state_ownership() {
  local state_resources resource_group_exists
  state_resources="$(tf_wrap state list 2>/dev/null || true)"
  resource_group_exists="$(az_wrap group exists --name "$TARGET_RESOURCE_GROUP")"

  if [[ "$resource_group_exists" == "true" ]] && ! grep -qx "azurerm_resource_group.demo" <<<"$state_resources"; then
    echo "Azure resource group $TARGET_RESOURCE_GROUP exists, but this checkout does not own it in Terraform state." >&2
    echo "Restore the original infra/terraform.tfstate or follow infra/README.md state recovery before deploying." >&2
    exit 1
  fi

  local app_id
  app_id="/subscriptions/$TARGET_SUBSCRIPTION/resourceGroups/$TARGET_RESOURCE_GROUP/providers/Microsoft.App/containerApps/foundry-image-models-demo"
  if az_wrap rest --method get \
    --url "https://management.azure.com${app_id}?api-version=2026-03-02-preview" \
    --only-show-errors >/dev/null 2>&1 \
    && ! grep -Fqx "azapi_resource.container_app[0]" <<<"$state_resources"; then
    echo "Container App foundry-image-models-demo exists, but it is missing from this checkout's Terraform state." >&2
    echo "Restore or import state before deploying; automatic recreation is disabled." >&2
    exit 1
  fi
}

load_current_auth_config() {
  local state_resources app_id app_json auth_values configured_count
  state_resources="$(tf_wrap state list)"
  if ! grep -Fqx "azapi_resource.container_app[0]" <<<"$state_resources"; then
    return 0
  fi

  app_id="$(tf_wrap output -raw container_app_id)"
  app_json="$(az_wrap rest --method get \
    --url "https://management.azure.com${app_id}?api-version=2026-03-02-preview" \
    -o json)"
  auth_values="$(printf '%s' "$app_json" | python3 -c "
import json, sys
app = json.load(sys.stdin)
env = {
    item.get('name'): item
    for item in app['properties']['template']['containers'][0].get('env', [])
    if isinstance(item, dict) and isinstance(item.get('name'), str)
}
values = [
    env.get('PUBLIC_BASE_URL', {}).get('value', ''),
    env.get('ENTRA_CLIENT_ID', {}).get('value', ''),
    env.get('ENTRA_CLIENT_SECRET', {}).get('secretRef', ''),
    env.get('SESSION_SECRET', {}).get('secretRef', ''),
]
print('|'.join(values))
")"
  IFS='|' read -r \
    CURRENT_PUBLIC_BASE_URL \
    CURRENT_ENTRA_CLIENT_ID \
    CURRENT_ENTRA_CLIENT_SECRET_NAME \
    CURRENT_SESSION_SECRET_NAME <<<"$auth_values"

  configured_count=0
  for value in \
    "$CURRENT_PUBLIC_BASE_URL" \
    "$CURRENT_ENTRA_CLIENT_ID" \
    "$CURRENT_ENTRA_CLIENT_SECRET_NAME" \
    "$CURRENT_SESSION_SECRET_NAME"; do
    [[ -n "$value" ]] && configured_count=$((configured_count + 1))
  done
  if [[ "$configured_count" -ne 0 && "$configured_count" -ne 4 ]]; then
    echo "Existing Container App authentication configuration is incomplete; refusing to overwrite it." >&2
    return 1
  fi
}

cleanup() {
  rm -rf "$BUILD_CONTEXT"
  rm -f "$PLAN_FILE"
}
trap cleanup EXIT

check_subscription() {
  local current
  current="$(az_wrap account show --query id -o tsv)"
  if [[ "$current" != "$TARGET_SUBSCRIPTION" ]]; then
    echo "Expected subscription $TARGET_SUBSCRIPTION but Azure CLI is on $current" >&2
    exit 1
  fi
}

register_provider() {
  local namespace="$1"
  local state
  state="$(az_wrap provider show --namespace "$namespace" --query registrationState -o tsv)"
  if [[ "$state" != "Registered" ]]; then
    az_wrap provider register --namespace "$namespace" --wait --only-show-errors >/dev/null
  fi
}

prepare_build_context() {
  rm -rf "$BUILD_CONTEXT"
  mkdir -p "$BUILD_CONTEXT"
  cp "$ROOT_DIR/Dockerfile" "$BUILD_CONTEXT/Dockerfile"
  cp "$ROOT_DIR/requirements.txt" "$BUILD_CONTEXT/requirements.txt"
  cp -R "$ROOT_DIR/app" "$BUILD_CONTEXT/app"
  cp -R "$ROOT_DIR/scripts" "$BUILD_CONTEXT/scripts"
  cp -R "$ROOT_DIR/static" "$BUILD_CONTEXT/static"
}

terraform_apply_foundation() {
  tf_wrap fmt -check -recursive
  tf_wrap init -input=false
  tf_wrap validate
  verify_local_state_ownership
  load_current_auth_config
  current_container_image >/dev/null
  if [[ "$CONTAINER_APP_EXISTS" == "true" ]]; then
    tf_wrap plan -input=false -out="$PLAN_FILE" \
      -target=azurerm_resource_group.demo \
      -target=azurerm_virtual_network.demo \
      -target=azurerm_subnet.apps \
      -target=azurerm_user_assigned_identity.demo \
      -target=azurerm_container_registry.acr \
      -target=azurerm_role_assignment.acr_pull \
      -target=azurerm_role_assignment.foundry_reader \
      -target=azurerm_role_assignment.foundry_cognitive_services_user \
      -target=azapi_resource.express_environment \
      "${TF_COMMON_VARS[@]}"
  else
    tf_wrap plan -input=false -out="$PLAN_FILE" \
      "${TF_COMMON_VARS[@]}"
  fi
  tf_wrap apply -input=false -auto-approve "$PLAN_FILE"
}

build_image_and_apply_app() {
  local acr_login_server
  acr_login_server="$(tf_wrap output -raw acr_login_server)"

  az_wrap acr build \
    --registry "$TARGET_ACR_NAME" \
    --image "${IMAGE_REPO}:${IMAGE_TAG}" \
    --file "$BUILD_CONTEXT/Dockerfile" \
    "$BUILD_CONTEXT" >/dev/null

  local digest
  digest="$(az_wrap acr repository show-manifests \
    --name "$TARGET_ACR_NAME" \
    --repository "$IMAGE_REPO" \
    --query "[?contains(tags, '${IMAGE_TAG}')].digest | [0]" -o tsv)"

  if [[ -z "$digest" ]]; then
    echo "ACR build completed but the image digest could not be resolved." >&2
    exit 1
  fi

  BUILT_IMAGE="${acr_login_server}/${IMAGE_REPO}@${digest}"
  if [[ "$CONTAINER_APP_EXISTS" == "false" ]]; then
    tf_wrap plan -input=false -out="$PLAN_FILE" \
      "${TF_COMMON_VARS[@]}" \
      -var="container_image=$BUILT_IMAGE"
    tf_wrap apply -input=false -auto-approve "$PLAN_FILE"
  fi
}

verify_managed_environment() {
  local env_id
  env_id="$(tf_wrap output -raw managed_environment_id)"
  az_wrap rest --method get \
    --url "https://management.azure.com${env_id}?api-version=2026-03-02-preview" \
    --query "properties.environmentMode" -o tsv | grep -qx "Express"
}

verify_container_app() {
  local app_id fqdn origin identity_id app_json
  app_id="$(tf_wrap output -raw container_app_id)"
  fqdn="$(container_app_fqdn)"
  identity_id="$(tf_wrap output -raw identity_id)"
  origin="https://${fqdn}"

  app_json="$(az_wrap rest --method get \
    --url "https://management.azure.com${app_id}?api-version=2026-03-02-preview" \
    -o json)"
  printf '%s' "$app_json" | python3 -c "
import json, sys
app = json.load(sys.stdin)
identity = app.get('identity', {})
assert identity.get('type') == 'UserAssigned', identity
bound = identity.get('userAssignedIdentities', {})
assert {key.lower() for key in bound} == {'$identity_id'.lower()}, bound
configuration = app['properties']['configuration']
registries = configuration.get('registries', [])
assert any(str(reg.get('identity', '')).lower() == '$identity_id'.lower() for reg in registries), registries
scale = app['properties']['template']['scale']
assert scale['minReplicas'] == 0, scale
assert scale['maxReplicas'] == 1, scale
assert any(rule.get('name') == 'http' for rule in scale.get('rules', [])), scale
"

  curl -fsS "$origin/healthz" >/dev/null

  local headers
  headers="$(curl -sS -D - -o /dev/null "$origin/" | tr -d '\r')"
  if ! grep -Eiq '^location: .*(/login|login.microsoftonline.com|entra)' <<<"$headers"; then
    echo "Expected unauthenticated / to redirect to login or Entra." >&2
    exit 1
  fi
}

main() {
  check_subscription
  for namespace in Microsoft.App Microsoft.ContainerRegistry Microsoft.ManagedIdentity Microsoft.Network Microsoft.Authorization Microsoft.CognitiveServices; do
    register_provider "$namespace"
  done

  prepare_build_context
  terraform_apply_foundation
  TARGET_ACR_NAME="$(tf_wrap output -raw acr_name)"
  build_image_and_apply_app

  local app_output
  local origin
  local configure_args=()
  origin="https://$(container_app_fqdn)"
  if [[ "$CONTAINER_APP_EXISTS" == "true" ]]; then
    configure_args+=(--image-only)
  fi
  app_output="$("$PYTHON_BIN" "$ROOT_DIR/scripts/configure_entra.py" \
    --container-app-id "$(tf_wrap output -raw container_app_id)" \
    --origin "$origin" \
    --display-name "foundry-image-models-demo" \
    --subscription-id "$TARGET_SUBSCRIPTION" \
    --resource-group "$TARGET_RESOURCE_GROUP" \
    --tenant-id "$TARGET_TENANT_ID" \
    --container-image "$BUILT_IMAGE" \
    --identity-client-id "$(tf_wrap output -raw identity_client_id)" \
    "${configure_args[@]}")"
  printf '%s\n' "$app_output"

  verify_managed_environment
  verify_container_app
}

main "$@"
