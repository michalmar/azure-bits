"""Configure only the demo registration and runtime, keeping secrets in memory."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit

from azure.identity import AzureCliCredential
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--image")
    args = parser.parse_args()
    settings_path = Path(args.settings)
    settings = json.loads(settings_path.read_text())
    if not settings.get("foundryAccountId"):
        raise ValueError("Settings must include the existing Foundry account ID as foundryAccountId")
    credential = AzureCliCredential()
    client = httpx.Client(timeout=90)
    arm = "https://management.azure.com"
    graph = "https://graph.microsoft.com/v1.0"

    def request(method, base, path, body=None):
        scope = "https://graph.microsoft.com/.default" if base == graph else "https://management.azure.com/.default"
        token = credential.get_token(scope).token
        response = client.request(method, base + path, json=body, headers={"Authorization": f"Bearer {token}"})
        if response.is_error:
            # Never include Graph addPassword or ARM secret bodies in diagnostics.
            raise RuntimeError(f"{method} {path.split('?')[0]} failed: HTTP {response.status_code}")
        return response.json() if response.content else {}

    app_path = settings["appId"] + "?api-version=2026-03-02-preview"
    snapshot = request("GET", arm, app_path)
    origin = "https://" + snapshot["properties"]["configuration"]["ingress"]["fqdn"]
    if not urlsplit(origin).hostname.endswith(".azurecontainerapps.io"):
        raise RuntimeError("Expected the actual Container Apps HTTPS origin")
    callback = origin + "/oauth/entra/callback"
    name = "foundry-mai-audio-demo"
    applications = request("GET", graph, f"/applications?$filter=displayName eq '{name}'")["value"]
    if len(applications) > 1:
        raise RuntimeError("Multiple registrations match; select the intended one manually")
    if applications:
        registration = applications[0]
        if registration.get("signInAudience") != "AzureADMyOrg":
            raise RuntimeError("Existing registration is not single-tenant")
        redirects = registration.get("web", {}).get("redirectUris", [])
        if callback not in redirects:
            request("PATCH", graph, "/applications/" + registration["id"],
                    {"web": {"redirectUris": redirects + [callback]}})
    else:
        registration = request("POST", graph, "/applications", {
            "displayName": name, "signInAudience": "AzureADMyOrg",
            "web": {"redirectUris": [callback]},
        })
        request("POST", graph, "/servicePrincipals", {"appId": registration["appId"]})
    expiry = (datetime.now(timezone.utc) + timedelta(days=180)).isoformat()
    password = request("POST", graph, f"/applications/{registration['id']}/addPassword", {
        "passwordCredential": {"displayName": name + "-reader-login", "endDateTime": expiry},
    })
    applied = False
    try:
        old = request("POST", arm, settings["appId"] + "/listSecrets?api-version=2026-03-02-preview", {})
        secret_values = {item["name"]: item["value"] for item in old.get("value", [])}
        secret_values.update({"session": secrets.token_urlsafe(48), "oauth-client": password["secretText"]})
        configuration = snapshot["properties"]["configuration"]
        configuration["secrets"] = [{"name": name, "value": value} for name, value in secret_values.items()]
        runtime = {
            "AUTH_PROVIDER": {"value": "entra"},
            "PUBLIC_BASE_URL": {"value": origin},
            "ALLOWED_USERS": {"value": "tenant:*"},
            "ENTRA_TENANT_ID": {"value": args.tenant},
            "ENTRA_CLIENT_ID": {"value": registration["appId"]},
            "ENTRA_CLIENT_SECRET": {"secretRef": "oauth-client"},
            "SESSION_SECRET": {"secretRef": "session"},
            "LIVE_AUDIO_ENABLED": {"value": "true"},
            "FOUNDRY_ACCOUNT_ID": {"value": settings["foundryAccountId"]},
            "UPLOAD_API_ENABLED": {"value": "false"},
        }
        container = snapshot["properties"]["template"]["containers"][0]
        container["env"] = [item for item in container["env"] if item["name"] not in runtime and item["name"] != "UPLOAD_API_TOKEN_SHA256"]
        container["env"] += [{"name": name, **value} for name, value in runtime.items()]
        if args.image:
            container["image"] = args.image
        payload = {key: snapshot[key] for key in ("location", "identity", "properties")}
        # Read-only response properties are not part of the mutation.
        properties = payload["properties"]
        payload["properties"] = {
            "environmentId": properties.get("environmentId") or properties["managedEnvironmentId"],
            "configuration": configuration,
            "template": properties["template"],
        }
        configuration["ingress"].pop("fqdn", None)
        configuration["ingress"].pop("traffic", None)
        properties["template"].pop("revisionSuffix", None)
        request("PUT", arm, app_path, payload)

        def wait_provisioning():
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline:
                state = request("GET", arm, app_path)["properties"]["provisioningState"]
                if state == "Succeeded":
                    return
                if state in {"Failed", "Canceled"}:
                    raise RuntimeError("Container App provisioning failed")
                time.sleep(5)
            raise RuntimeError("Container App provisioning timed out")

        wait_provisioning()
        request("POST", arm, settings["appId"] + "/stop?api-version=2026-03-02-preview", {})
        wait_provisioning()
        request("POST", arm, settings["appId"] + "/start?api-version=2026-03-02-preview", {})
        wait_provisioning()
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            try:
                response = client.get(origin + "/healthz", timeout=20)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(5)
        else:
            raise RuntimeError("Runtime did not become healthy; registration password retained for recovery")
        if client.get(origin, follow_redirects=False).status_code != 302:
            raise RuntimeError("Reader protection verification failed")
        if client.get(origin + "/api/config").status_code != 401:
            raise RuntimeError("Playground API is not reader-protected")
        applied = True
        settings.update(origin=origin, entraApplicationId=registration["appId"],
                        entraApplicationObjectId=registration["id"], readerCredentialKeyId=password["keyId"],
                        readerCredentialExpiresAt=expiry)
        settings_path.write_text(json.dumps(settings, indent=2))
        print(json.dumps({"origin": origin, "reader": "single-tenant Entra", "credentialExpiresAt": expiry}))
    finally:
        # Preserve an applied credential if verification fails; it may already be in use.
        if not applied:
            print("Configuration incomplete. Keep the deployment settings and inspect runtime before retrying.")
        client.close()


if __name__ == "__main__":
    main()
