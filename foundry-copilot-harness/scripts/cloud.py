"""Narrow administrative helpers. Credentials stay in memory and out of argv/logs."""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import time

import httpx

os.environ["AZURE_CONFIG_DIR"] = os.path.expanduser("~/.azure-365")
os.environ["AZD_CONFIG_DIR"] = os.path.expanduser("~/.azd-365")
SUBSCRIPTION = "7bc68c68-f434-49ad-ab3e-b883ec39da86"
ROOT = f"/subscriptions/{SUBSCRIPTION}/resourceGroups"
APP_ID = f"{ROOT}/rg-foundry-copilot-harness-demo/providers/Microsoft.App/containerApps/foundry-copilot-harness-demo"
SOURCE_APP_ID = f"{ROOT}/rg-foundry-mai-audio-demo/providers/Microsoft.App/containerApps/foundry-mai-audio-demo"
STORAGE_SCOPE = f"{ROOT}/rg-foundry-mai-audio-demo/providers/Microsoft.Storage/storageAccounts/maiaudio7bc68/blobServices/default/containers/site"
PRINCIPAL = "806dd425-eee0-43cb-b87f-d557f998cc84"
API = "2026-03-02-preview"


class AzureOperationError(RuntimeError):
    def __init__(self, operation: str, code: str):
        super().__init__(f"Azure operation {operation} failed: {code} (credential-bearing details suppressed)")
        self.code = code


def az(*args: str, body: dict | None = None):
    command = ["az", *args, "--only-show-errors", "-o", "json"]
    data = None
    if body is not None:
        command.extend(["--body", "@-"])
        data = json.dumps(body)
    result = subprocess.run(command, input=data, capture_output=True, text=True)
    if result.returncode:
        match = re.search(r'"code"\s*:\s*"([A-Za-z0-9_]+)"', result.stderr)
        raise AzureOperationError(" ".join(args[:2]), match[1] if match else "CommandFailed")
    return json.loads(result.stdout) if result.stdout.strip() else None


def arm(identifier: str, *, action: str = "", body: dict | None = None, method: str = "get"):
    for attempt in range(36):
        try:
            return az(
                "rest", "--method", method, "--url",
                f"https://management.azure.com{identifier}{action}?api-version={API}", body=body,
            )
        except AzureOperationError as exc:
            if exc.code not in {"ContainerAppOperationInProgress", "UnexpectedException"} or attempt == 35:
                raise
            time.sleep(5)
    raise RuntimeError("Azure operation retry limit exhausted")


def env_values(app: dict) -> dict[str, str]:
    return {
        item["name"]: item["value"]
        for item in app["properties"]["template"]["containers"][0].get("env", [])
        if "value" in item
    }


def update_app(*, values: dict[str, str] | None = None, secrets: dict[str, str] | None = None, image: str | None = None):
    current = arm(APP_ID)
    properties = copy.deepcopy(current["properties"])
    configuration = properties["configuration"]
    # Read-only fields aren't accepted by all Express API revisions.
    for key in ["latestRevisionName", "latestReadyRevisionName", "latestRevisionFqdn", "eventStreamEndpoint", "outboundIpAddresses", "provisioningState", "runningStatus", "customDomainVerificationId"]:
        properties.pop(key, None)
    existing_secrets = configuration.get("secrets") or []
    unresolved = [
        item for item in existing_secrets
        if not item.get("keyVaultUrl") and not item.get("value")
    ]
    if unresolved:
        secret_values = {
            item["name"]: item.get("value")
            for item in arm(APP_ID, action="/listSecrets", method="post")["value"]
        }
        for item in unresolved:
            value = secret_values.get(item["name"])
            if not value:
                raise RuntimeError("Existing app secret cannot be preserved; update aborted")
            item["value"] = value
    configuration["secrets"] = existing_secrets
    container = properties["template"]["containers"][0]
    if image:
        if not re.fullmatch(r"maiaudio7bc68\.azurecr\.io/copilot-harness@sha256:[0-9a-f]{64}", image):
            raise ValueError("Use a reviewed immutable digest in this demo's image repository")
        container["image"] = image
    if values:
        env = {item["name"]: item for item in container.get("env", [])}
        env.update({name: {"name": name, "value": value} for name, value in values.items()})
        container["env"] = list(env.values())
    if secrets:
        existing = {item["name"]: item for item in configuration.get("secrets") or []}
        existing.update({name: {"name": name, "value": value} for name, value in secrets.items()})
        configuration["secrets"] = list(existing.values())
    # Preserve the existing identity, registries, probes, scale and auth-related fields.
    arm(APP_ID, method="patch", body={"properties": properties})
    arm(APP_ID, action="/stop", method="post")
    arm(APP_ID, action="/start", method="post")
    return "https://" + current["properties"]["configuration"]["ingress"]["fqdn"]


def wait_status(origin: str, path: str, status: int, *, headers=None, attempts=60, method="GET"):
    for _ in range(attempts):
        try:
            response = httpx.request(method, origin + path, headers=headers, timeout=15, follow_redirects=False)
            if response.status_code == status:
                return
        except httpx.HTTPError:
            pass
        time.sleep(5)
    raise RuntimeError(f"Timed out waiting for {path} to return {status}")
