"""Publish only named static assets through the scoped relay; always lock it down."""

import argparse
import hashlib
import json
import mimetypes
from pathlib import Path
import secrets
import time
import uuid

import httpx

from cloud import APP_ID, PRINCIPAL, STORAGE_SCOPE, az, update_app, wait_status

ROOT = Path(__file__).resolve().parent.parent
MARKER = ROOT / ".aca-publish-recovery.json"
ASSETS = ["tokens.css", "baseline.css", "style.css", "app.mjs", "index.html"]


def verify_relay(client, origin, headers):
    for authorization in [None, "Bearer " + "invalid" * 8]:
        probe_headers = {"Authorization": authorization} if authorization else {}
        if client.get(origin + "/_publish/blobs", headers=probe_headers).status_code != 401:
            raise RuntimeError("Enabled publishing API did not reject an invalid credential")
    path = origin + "/_publish/blobs/publish-check.txt"
    try:
        for content in [b"initial", b"verified overwrite"]:
            client.put(path, content=content, headers={**headers, "Content-Type": "text/plain"}).raise_for_status()
            response = client.get(path, headers=headers)
            response.raise_for_status()
            if response.content != content:
                raise RuntimeError("Relay overwrite verification failed")
        if client.head(path, headers=headers).headers.get("content-length") != "18":
            raise RuntimeError("Relay HEAD verification failed")
        response = client.get(path, headers={**headers, "Range": "bytes=0-7"})
        if response.status_code != 206 or response.content != b"verified":
            raise RuntimeError("Relay range verification failed")
        if client.get(path, headers={**headers, "Range": "bytes=999-1000"}).status_code != 416:
            raise RuntimeError("Relay invalid-range verification failed")
        response = client.put(
            path, content=b"x" * (2 * 1024 * 1024 + 1),
            headers={**headers, "Content-Type": "text/plain"},
        )
        if response.status_code != 413 or client.get(path, headers=headers).content != b"verified overwrite":
            raise RuntimeError("Oversized upload did not preserve the committed blob")
    finally:
        client.delete(path, headers=headers).raise_for_status()
    if client.get(path, headers=headers).status_code != 404:
        raise RuntimeError("Relay exact-delete verification failed")
    names, cursor = set(), None
    while True:
        response = client.get(origin + "/_publish/blobs", headers=headers, params={"cursor": cursor} if cursor else {})
        response.raise_for_status()
        page = response.json()
        names.update(item["path"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    if names != set(ASSETS):
        raise RuntimeError("Relay listing does not match this demo's exact asset set")


def lockdown(role_id: str | None):
    failure = None
    try:
        origin = update_app(values={"UPLOAD_API_ENABLED": "false", "UPLOAD_API_TOKEN_SHA256": ""})
        for method in ["GET", "HEAD", "PUT", "DELETE"]:
            wait_status(origin, "/_publish/blobs/index.html", 404, method=method, attempts=24)
        wait_status(origin, "/_publish/blobs", 404, attempts=24)
    except (RuntimeError, httpx.HTTPError) as exc:
        failure = exc
    finally:
        if role_id:
            az("role", "assignment", "delete", "--ids", role_id)
    if failure:
        raise failure
    MARKER.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--approve-publish-role", action="store_true")
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    if args.recover:
        if not MARKER.exists():
            raise RuntimeError("No exact recovery marker exists")
        marker = json.loads(MARKER.read_text())
        prefix = f"{STORAGE_SCOPE}/providers/Microsoft.Authorization/roleAssignments/"
        role_id = marker["role_id"]
        if (
            marker.get("app_id") != APP_ID or marker.get("storage_scope") != STORAGE_SCOPE
            or marker.get("identity_principal_id") != PRINCIPAL
            or not isinstance(role_id, str) or not role_id.startswith(prefix)
            or str(uuid.UUID(role_id.removeprefix(prefix))) != role_id.removeprefix(prefix)
        ):
            raise ValueError("Recovery marker does not identify this app's exact temporary assignment")
        lockdown(role_id)
        return
    if not args.approve_publish_role:
        parser.error("Explicit approval is required for a temporary container-scoped Contributor assignment")
    if MARKER.exists():
        raise RuntimeError("Recover the previous publish before starting another")
    # Exclusive creation is the publishing lock and durable recovery marker.
    role_name = str(uuid.uuid4())
    role_id = f"{STORAGE_SCOPE}/providers/Microsoft.Authorization/roleAssignments/{role_name}"
    with MARKER.open("x", encoding="utf-8") as stream:
        json.dump({
            "app_id": APP_ID, "role_id": role_id,
            "storage_scope": STORAGE_SCOPE, "identity_principal_id": PRINCIPAL,
        }, stream)
    token = secrets.token_urlsafe(48)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        az(
            "role", "assignment", "create", "--name", role_name, "--scope", STORAGE_SCOPE,
            "--assignee-object-id", PRINCIPAL, "--assignee-principal-type", "ServicePrincipal",
            "--role", "Storage Blob Data Contributor",
        )
        origin = update_app(values={
            "UPLOAD_API_ENABLED": "true",
            "UPLOAD_API_TOKEN_SHA256": hashlib.sha256(token.encode()).hexdigest(),
            "MAX_UPLOAD_BYTES": "2097152",
        })
        wait_status(origin, "/_publish/blobs", 200, headers=headers)
        with httpx.Client(timeout=60, follow_redirects=False) as client:
            for name in ASSETS:
                path = ROOT / "static" / name
                if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError("Only small regular static assets may be uploaded")
                mime = "text/javascript" if name.endswith(".mjs") else mimetypes.guess_type(name)[0]
                for attempt in range(24):
                    response = client.put(
                        origin + "/_publish/blobs/" + name, content=path.read_bytes(),
                        headers={**headers, "Content-Type": mime or "application/octet-stream"},
                    )
                    if response.status_code != 503:
                        break
                    time.sleep(5)
                response.raise_for_status()
                verify = client.get(origin + "/_publish/blobs/" + name, headers=headers)
                verify.raise_for_status()
                if verify.content != path.read_bytes():
                    raise RuntimeError("Published asset did not match local bytes")
            verify_relay(client, origin, headers)
        print("Static assets uploaded and byte-verified in the demo-only prefix.")
    finally:
        lockdown(role_id)
    print("Upload relay disabled and temporary Contributor assignment removed.")


if __name__ == "__main__":
    main()
