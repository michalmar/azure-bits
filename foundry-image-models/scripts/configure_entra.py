#!/usr/bin/env python3
"""Configure the demo's Entra app registration and Container App auth settings."""

from __future__ import annotations

import argparse
import copy
import json
import secrets
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from azure.identity import AzureCliCredential


GRAPH_BASE = "https://graph.microsoft.com/v1.0"
ARM_BASE = "https://management.azure.com"
ARM_API_VERSION = "2026-03-02-preview"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
ARM_SCOPE = "https://management.azure.com/.default"
PASSWORD_LABEL = "foundry-image-models-auth"
SESSION_SECRET_LABEL = "foundry-image-models-session"
MAX_RETRIES = 3


class PreconditionFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class Result:
    application_id: str
    application_object_id: str
    service_principal_id: str
    client_id: str
    redirect_uri: str
    credential_key_id: str | None
    credential_expires_at: str | None
    container_app_id: str
    public_base_url: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "applicationId": self.application_id,
                "applicationObjectId": self.application_object_id,
                "servicePrincipalId": self.service_principal_id,
                "clientId": self.client_id,
                "redirectUri": self.redirect_uri,
                "credentialKeyId": self.credential_key_id,
                "credentialExpiresAt": self.credential_expires_at,
                "containerAppId": self.container_app_id,
                "publicBaseUrl": self.public_base_url,
            },
            indent=2,
            sort_keys=True,
        )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def access_token(scope: str) -> str:
    return AzureCliCredential().get_token(scope).token


def _send(
    method: str,
    base_url: str,
    path: str,
    scope: str,
    *,
    body: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    headers = _headers(access_token(scope))
    if extra_headers:
        headers.update(extra_headers)
    with httpx.Client(timeout=60.0) as client:
        response = client.request(method, f"{base_url}{path}", headers=headers, json=body)
    if response.status_code == 412:
        raise PreconditionFailed(f"{method} {path} precondition failed")
    if response.is_error:
        detail = response.text.strip()
        if len(detail) > 2000:
            detail = f"{detail[:2000]}..."
        raise RuntimeError(f"{method} {path} failed with {response.status_code}: {detail}")
    return response


def graph_request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    return _send(method, GRAPH_BASE, path, GRAPH_SCOPE, body=body, extra_headers=extra_headers)


def arm_request(
    method: str,
    resource_id: str,
    *,
    body: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    return _send(
        method,
        ARM_BASE,
        f"{resource_id}?api-version={ARM_API_VERSION}",
        ARM_SCOPE,
        body=body,
        extra_headers=extra_headers,
    )


def _graph_json(path: str) -> dict[str, Any]:
    return graph_request("GET", path).json()


def _arm_json(resource_id: str) -> dict[str, Any]:
    return arm_request("GET", resource_id).json()


def _container_app_secret_values(app_id: str) -> dict[str, str]:
    response = arm_request("POST", f"{app_id}/listSecrets", body={})
    payload = response.json()
    values: dict[str, str] = {}
    for item in payload.get("value", []) or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if isinstance(name, str) and name and isinstance(value, str) and value:
            values[name] = value
    return values


def _hydrate_container_app_secrets(snapshot: dict[str, Any], values: dict[str, str]) -> None:
    secrets_list = snapshot["properties"]["configuration"].get("secrets", []) or []
    for item in secrets_list:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name in values:
            item["value"] = values[name]


def _snapshot_secret_values(snapshot: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    secrets_list = snapshot["properties"]["configuration"].get("secrets", []) or []
    for item in secrets_list:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if isinstance(name, str) and name and isinstance(value, str) and value:
            values[name] = value
    return values


def _etag(payload: dict[str, Any], response: httpx.Response | None = None) -> str | None:
    for key in ("@odata.etag", "etag"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    if response is not None:
        for key in ("etag", "ETag"):
            value = response.headers.get(key)
            if value:
                return value
    return None


def _single_match(items: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    if len(items) > 1:
        raise RuntimeError(f"multiple {label} matches found; refusing to guess")
    return items[0] if items else None


def _matching_passwords(app: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in app.get("passwordCredentials", []) or []
        if isinstance(item, dict) and item.get("displayName") == PASSWORD_LABEL
    ]


def _container_secret_ref(app: dict[str, Any]) -> str | None:
    containers = app.get("properties", {}).get("template", {}).get("containers", []) or []
    if not containers:
        return None
    for item in containers[0].get("env", []) or []:
        if isinstance(item, dict) and item.get("name") == "ENTRA_CLIENT_SECRET":
            ref = item.get("secretRef")
            return ref if isinstance(ref, str) and ref else None
    return None


def _secret_names(app: dict[str, Any]) -> list[str]:
    return [
        item["name"]
        for item in app.get("properties", {}).get("configuration", {}).get("secrets", []) or []
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]


def _build_secret_name(key_id: str) -> str:
    suffix = key_id.replace("-", "").lower()[:8]
    return f"{PASSWORD_LABEL}-{suffix}"


def find_application(display_name: str) -> dict[str, Any] | None:
    safe_display_name = display_name.replace("'", "''")
    query = (
        "$select=id,appId,displayName,web,passwordCredentials,signInAudience"
        f"&$filter=displayName eq '{safe_display_name}'"
    )
    payload = _graph_json(f"/applications?{query}")
    matches = [item for item in payload.get("value", []) if isinstance(item, dict)]
    return _single_match(matches, "application")


def create_application(display_name: str, redirect_uri: str) -> dict[str, Any]:
    response = graph_request(
        "POST",
        "/applications",
        body={
            "displayName": display_name,
            "signInAudience": "AzureADMyOrg",
            "web": {
                "redirectUris": [redirect_uri],
                "implicitGrantSettings": {
                    "enableIdTokenIssuance": False,
                    "enableAccessTokenIssuance": False,
                },
            },
        },
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Graph did not return the created application")
    return payload


def ensure_application(display_name: str, redirect_uri: str) -> dict[str, Any]:
    for _ in range(MAX_RETRIES):
        app = find_application(display_name)
        if app is None:
            return create_application(display_name, redirect_uri)
        redirect_uris = list((app.get("web") or {}).get("redirectUris") or [])
        if redirect_uri in redirect_uris:
            return app
        desired_redirects = list(dict.fromkeys([*redirect_uris, redirect_uri]))
        etag = _etag(app)
        headers = {"If-Match": etag} if etag else None
        try:
            response = graph_request(
                "PATCH",
                f"/applications/{app['id']}",
                body={"web": {"redirectUris": desired_redirects}},
                extra_headers=headers,
            )
        except PreconditionFailed:
            continue
        if response.content:
            updated = response.json()
            if isinstance(updated, dict):
                return updated
        app["web"] = {**(app.get("web") or {}), "redirectUris": desired_redirects}
        return app
    raise RuntimeError("failed to update redirect URI after concurrent edits")


def ensure_service_principal(app_id: str) -> dict[str, Any]:
    query = f"$select=id,appId&$filter=appId eq '{app_id}'"
    payload = _graph_json(f"/servicePrincipals?{query}")
    matches = [item for item in payload.get("value", []) if isinstance(item, dict)]
    sp = _single_match(matches, "service principal")
    if sp is not None:
        return sp
    response = graph_request("POST", "/servicePrincipals", body={"appId": app_id})
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Graph did not return the created service principal")
    return payload


def create_client_secret(app_id: str) -> tuple[str, str, str]:
    end = datetime.now(timezone.utc) + timedelta(days=365)
    response = graph_request(
        "POST",
        f"/applications/{app_id}/addPassword",
        body={
            "passwordCredential": {
                "displayName": PASSWORD_LABEL,
                "endDateTime": end.isoformat().replace("+00:00", "Z"),
            }
        },
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Graph did not return the created password credential")
    secret_text = payload.get("secretText")
    key_id = payload.get("keyId")
    expires = payload.get("endDateTime")
    if not all(isinstance(value, str) and value for value in (secret_text, key_id, expires)):
        raise RuntimeError("Graph password credential response was incomplete")
    return secret_text, key_id, expires


def remove_client_secret(app_id: str, key_id: str) -> None:
    graph_request("POST", f"/applications/{app_id}/removePassword", body={"keyId": key_id})


def _writable_configuration(configuration: dict[str, Any]) -> dict[str, Any]:
    writable = copy.deepcopy(configuration)
    ingress = writable.get("ingress")
    if isinstance(ingress, dict):
        ingress.pop("fqdn", None)
    return writable


def _writable_template(template: dict[str, Any]) -> dict[str, Any]:
    writable = copy.deepcopy(template)
    for container in writable.get("containers", []) or []:
        if isinstance(container, dict):
            container.pop("imageType", None)
    for container in writable.get("initContainers", []) or []:
        if isinstance(container, dict):
            container.pop("imageType", None)
    return writable


def _apply_container_app_snapshot(snapshot: dict[str, Any], *, extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
    body = {
        "location": snapshot["location"],
        "tags": snapshot.get("tags", {}),
        "identity": snapshot["identity"],
        "properties": {
            "managedEnvironmentId": snapshot["properties"]["managedEnvironmentId"],
            "configuration": _writable_configuration(snapshot["properties"]["configuration"]),
            "template": _writable_template(snapshot["properties"]["template"]),
        },
    }
    headers = dict(extra_headers or {})
    etag = _etag(snapshot)
    if etag and "If-Match" not in headers:
        headers["If-Match"] = etag
    response = arm_request("PUT", snapshot["id"], body=body, extra_headers=headers or None)
    if response.content:
        updated = response.json()
        if isinstance(updated, dict):
            return updated
    return snapshot


def _update_container_app(
    app_id: str,
    *,
    origin: str,
    app_client_id: str,
    identity_client_id: str,
    tenant_id: str,
    secret_name: str,
    secret_value: str | None,
    snapshot: dict[str, Any],
    session_secret_value: str | None = None,
    container_image: str | None = None,
) -> dict[str, Any]:
    preserved_secret_values = _snapshot_secret_values(snapshot)
    for _ in range(MAX_RETRIES):
        current = _arm_json(app_id)
        _hydrate_container_app_secrets(current, preserved_secret_values)
        if current["properties"].get("managedEnvironmentId") != snapshot["properties"].get("managedEnvironmentId"):
            snapshot = current
        containers = current["properties"]["template"].get("containers") or []
        if not containers:
            raise RuntimeError("container app has no containers")
        if container_image is not None:
            containers[0]["image"] = container_image
        env = list(containers[0].get("env", []))
        by_name = {item["name"]: item for item in env if isinstance(item, dict) and isinstance(item.get("name"), str)}
        by_name.update(
            {
                "AUTH_ENABLED": {"name": "AUTH_ENABLED", "value": "true"},
                "AUTH_PROVIDER": {"name": "AUTH_PROVIDER", "value": "entra"},
                "ENTRA_TENANT_ID": {"name": "ENTRA_TENANT_ID", "value": tenant_id},
                "ENTRA_CLIENT_ID": {"name": "ENTRA_CLIENT_ID", "value": app_client_id},
                "PUBLIC_BASE_URL": {"name": "PUBLIC_BASE_URL", "value": origin},
                "SESSION_SECRET": {"name": "SESSION_SECRET", "secretRef": SESSION_SECRET_LABEL},
                "ENTRA_CLIENT_SECRET": {"name": "ENTRA_CLIENT_SECRET", "secretRef": secret_name},
            }
        )
        containers[0]["env"] = [by_name[key] for key in sorted(by_name)]
        configuration = current["properties"]["configuration"]
        secrets_list = [
            item
            for item in configuration.get("secrets", []) or []
            if not (
                isinstance(item, dict)
                and isinstance(item.get("name"), str)
                and item["name"].startswith(f"{PASSWORD_LABEL}-")
                and item["name"] != secret_name
            )
        ]
        if secret_value is not None:
            secrets_list = [
                item
                for item in secrets_list
                if not (isinstance(item, dict) and item.get("name") == secret_name)
            ]
            secrets_list.append({"name": secret_name, "value": secret_value})
        if session_secret_value is not None:
            secrets_list = [
                item
                for item in secrets_list
                if not (isinstance(item, dict) and item.get("name") == SESSION_SECRET_LABEL)
            ]
            secrets_list.append({"name": SESSION_SECRET_LABEL, "value": session_secret_value})
        configuration["secrets"] = secrets_list
        body = {
            "location": current["location"],
            "tags": current.get("tags", {}),
            "identity": current["identity"],
            "properties": {
                "managedEnvironmentId": current["properties"]["managedEnvironmentId"],
                "configuration": _writable_configuration(configuration),
                "template": _writable_template(current["properties"]["template"]),
            },
        }
        etag = _etag(current)
        headers = {"If-Match": etag} if etag else None
        try:
            response = arm_request("PUT", app_id, body=body, extra_headers=headers)
        except PreconditionFailed:
            continue
        if response.content:
            updated = response.json()
            if isinstance(updated, dict):
                return updated
        return current
    raise RuntimeError("failed to update container app after concurrent edits")


def _update_container_image(
    app_id: str,
    *,
    container_image: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    preserved_secret_values = _snapshot_secret_values(snapshot)
    for _ in range(MAX_RETRIES):
        current = _arm_json(app_id)
        _hydrate_container_app_secrets(current, preserved_secret_values)
        containers = current["properties"]["template"].get("containers") or []
        if not containers:
            raise RuntimeError("container app has no containers")
        containers[0]["image"] = container_image
        try:
            return _apply_container_app_snapshot(current)
        except PreconditionFailed:
            continue
    raise RuntimeError("failed to update container image after concurrent edits")


def wait_for_container_app_provisioning(
    app_id: str,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_state = "Unknown"
    while time.monotonic() < deadline:
        current = _arm_json(app_id)
        last_state = str(current.get("properties", {}).get("provisioningState", "Unknown"))
        if last_state == "Succeeded":
            return current
        if last_state in {"Failed", "Canceled"}:
            raise RuntimeError(f"Container App provisioning ended in state {last_state}")
        time.sleep(5)
    raise RuntimeError(f"Container App provisioning did not complete; last state was {last_state}")


def stop_start_container_app(app_id: str) -> None:
    arm_request("POST", f"{app_id}/stop", body={})
    wait_for_container_app_provisioning(app_id)
    arm_request("POST", f"{app_id}/start", body={})
    wait_for_container_app_provisioning(app_id)


def _delete_superseded_passwords(app_id: str, keep_key_id: str) -> None:
    app = _graph_json(f"/applications/{app_id}?$select=id,passwordCredentials")
    current = [
        item
        for item in app.get("passwordCredentials", []) or []
        if isinstance(item, dict) and item.get("displayName") == PASSWORD_LABEL
    ]
    for item in current:
        key_id = item.get("keyId")
        if isinstance(key_id, str) and key_id and key_id != keep_key_id:
            remove_client_secret(app_id, key_id)
    refreshed = _graph_json(f"/applications/{app_id}?$select=id,passwordCredentials")
    remaining = [
        item.get("keyId")
        for item in refreshed.get("passwordCredentials", []) or []
        if isinstance(item, dict) and item.get("displayName") == PASSWORD_LABEL and isinstance(item.get("keyId"), str)
    ]
    if any(key_id != keep_key_id for key_id in remaining):
        raise RuntimeError("superseded Graph passwords were not fully removed")


def wait_for_health(origin: str, timeout_seconds: int = 900) -> None:
    deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
    while datetime.now(timezone.utc) < deadline:
        try:
            response = httpx.get(f"{origin}/healthz", timeout=20.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
    raise RuntimeError("Container App did not become healthy")


def verify_auth_redirect(origin: str) -> None:
    response = httpx.get(origin, follow_redirects=False, timeout=20.0)
    if response.status_code not in {301, 302, 303, 307, 308}:
        raise RuntimeError(f"expected a redirect from /, got {response.status_code}")
    location = response.headers.get("location", "")
    if not ("login" in location.lower() or "entra" in location.lower()):
        raise RuntimeError(f"expected a login redirect, got {location!r}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--container-app-id", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--subscription-id", required=False)
    parser.add_argument("--resource-group", required=False)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--identity-client-id", required=True)
    parser.add_argument("--container-image")
    parser.add_argument("--image-only", action="store_true")
    parser.add_argument("--rotate-client-secret", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    origin = args.origin.rstrip("/")
    redirect_uri = f"{origin}/oauth/entra/callback"
    app_id = args.container_app_id

    if args.subscription_id and f"/subscriptions/{args.subscription_id}/" not in app_id:
        raise RuntimeError("container app resource ID does not match the expected subscription")
    if args.resource_group and f"/resourceGroups/{args.resource_group}/" not in app_id:
        raise RuntimeError("container app resource ID does not match the expected resource group")

    if args.image_only:
        if not args.container_image:
            raise RuntimeError("--image-only requires --container-image")
        wait_for_container_app_provisioning(app_id)
        previous_app = _arm_json(app_id)
        _hydrate_container_app_secrets(previous_app, _container_app_secret_values(app_id))
        succeeded = False
        primary_error: Exception | None = None
        try:
            _update_container_image(
                app_id,
                container_image=args.container_image,
                snapshot=previous_app,
            )
            wait_for_container_app_provisioning(app_id)
            stop_start_container_app(app_id)
            wait_for_health(origin)
            verify_auth_redirect(origin)
            succeeded = True
        except Exception as exc:
            primary_error = exc
        finally:
            if not succeeded:
                cleanup_errors: list[Exception] = []
                try:
                    wait_for_container_app_provisioning(app_id)
                    _apply_container_app_snapshot(previous_app)
                    wait_for_container_app_provisioning(app_id)
                except Exception as exc:
                    cleanup_errors.append(exc)
                for cleanup_error in cleanup_errors:
                    print(f"cleanup error: {cleanup_error!r}", file=sys.stderr)
        if primary_error is not None:
            raise primary_error
        print(
            json.dumps(
                {
                    "containerAppId": app_id,
                    "containerImage": args.container_image,
                    "mode": "image-only",
                    "publicBaseUrl": origin,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    app = ensure_application(args.display_name, redirect_uri)
    principal = ensure_service_principal(app["appId"])
    wait_for_container_app_provisioning(app_id)
    previous_app = _arm_json(app_id)
    _hydrate_container_app_secrets(previous_app, _container_app_secret_values(app_id))
    current_secret_ref = _container_secret_ref(previous_app)
    current_passwords = _matching_passwords(app)
    existing_secret_names = {
        item.get("name")
        for item in previous_app["properties"]["configuration"].get("secrets", []) or []
        if isinstance(item, dict)
    }
    session_secret_value = (
        None if SESSION_SECRET_LABEL in existing_secret_names else secrets.token_urlsafe(48)
    )

    needs_new_secret = args.rotate_client_secret or not current_secret_ref or not current_passwords
    created_key_id: str | None = None
    credential_expires_at: str | None = None
    secret_name = current_secret_ref or ""
    secret_value: str | None = None
    if needs_new_secret:
        secret_value, created_key_id, credential_expires_at = create_client_secret(app["id"])
        secret_name = _build_secret_name(created_key_id)

    succeeded = False
    primary_error: Exception | None = None
    try:
        _update_container_app(
            app_id,
            origin=origin,
            app_client_id=app["appId"],
            identity_client_id=args.identity_client_id,
            tenant_id=args.tenant_id,
            secret_name=secret_name,
            secret_value=secret_value,
            session_secret_value=session_secret_value,
            container_image=args.container_image,
            snapshot=previous_app,
        )
        wait_for_container_app_provisioning(app_id)
        stop_start_container_app(app_id)
        wait_for_health(origin)
        verify_auth_redirect(origin)
        succeeded = True
        if created_key_id:
            _delete_superseded_passwords(app["id"], created_key_id)
    except Exception as exc:
        primary_error = exc
    finally:
        if not succeeded:
            cleanup_errors: list[Exception] = []
            try:
                wait_for_container_app_provisioning(app_id)
                _apply_container_app_snapshot(previous_app)
                wait_for_container_app_provisioning(app_id)
            except Exception as exc:
                cleanup_errors.append(exc)
            finally:
                if created_key_id:
                    try:
                        remove_client_secret(app["id"], created_key_id)
                    except Exception as exc:
                        cleanup_errors.append(exc)
            if primary_error is not None and cleanup_errors:
                for cleanup_error in cleanup_errors:
                    primary_error.add_note(f"cleanup error: {cleanup_error!r}")
            elif primary_error is None and cleanup_errors:
                if len(cleanup_errors) == 1:
                    raise cleanup_errors[0]
                raise ExceptionGroup("cleanup failed", cleanup_errors)

    if primary_error is not None:
        raise primary_error

    result = Result(
        application_id=app["appId"],
        application_object_id=app["id"],
        service_principal_id=principal["id"],
        client_id=app["appId"],
        redirect_uri=redirect_uri,
        credential_key_id=created_key_id,
        credential_expires_at=credential_expires_at,
        container_app_id=app_id,
        public_base_url=origin,
    )
    print(result.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
