"""Configure existing Entra reader settings only after explicit scoped approval."""

import argparse
import secrets

from cloud import APP_ID, SOURCE_APP_ID, arm, az, env_values, update_app, wait_status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--approve-reader-changes", action="store_true")
    parser.add_argument("--agent-version", required=True)
    args = parser.parse_args()
    if not args.approve_reader_changes:
        parser.error("Explicit approval is required to copy reader settings and add a redirect URI")
    if not args.agent_version.isdigit():
        parser.error("--agent-version must be a positive numeric published version")
    source = arm(SOURCE_APP_ID)
    target = arm(APP_ID)
    source_env = env_values(source)
    if source_env.get("AUTH_PROVIDER") != "entra" or not source_env.get("ALLOWED_USERS"):
        raise RuntimeError("The existing reader must use Entra and a nonempty allowlist")
    origin = "https://" + target["properties"]["configuration"]["ingress"]["fqdn"]
    callback = origin + "/oauth/entra/callback"
    registration = az("ad", "app", "show", "--id", source_env["ENTRA_CLIENT_ID"])
    callbacks = list(registration.get("web", {}).get("redirectUris", []))
    if callback not in callbacks:
        az("ad", "app", "update", "--id", registration["id"], "--web-redirect-uris", *callbacks, callback)
    # Existing app secret access is administrative. Nothing is printed or stored locally.
    source_secrets = arm(SOURCE_APP_ID, action="/listSecrets", method="post")
    secret_values = {item["name"]: item.get("value") for item in source_secrets["value"]}
    source_secret = next(
        item["secretRef"] for item in source["properties"]["template"]["containers"][0]["env"]
        if item["name"] == "ENTRA_CLIENT_SECRET"
    )
    credential = secret_values.get(source_secret)
    if not credential:
        raise RuntimeError("The approved existing reader credential is not retrievable")
    update_app(secrets={"reader-secret": credential, "session-secret": secrets.token_urlsafe(48)})
    current = arm(APP_ID)
    properties = current["properties"]
    env = {item["name"]: item for item in properties["template"]["containers"][0].get("env", [])}
    values = {
        "APP_ENV": "production", "LOCAL_DEV": "false", "LIVE_DEMO_ENABLED": "true",
        "UPLOAD_API_ENABLED": "false", "AUTH_PROVIDER": "entra", "PUBLIC_BASE_URL": origin,
        "ENTRA_CLIENT_ID": source_env["ENTRA_CLIENT_ID"], "ENTRA_TENANT_ID": source_env["ENTRA_TENANT_ID"],
        "ALLOWED_USERS": source_env["ALLOWED_USERS"],
        "AZURE_CLIENT_ID": "c631318a-ed22-43fb-b444-f85360564def",
        "STORAGE_ACCOUNT_NAME": "maiaudio7bc68", "BLOB_CONTAINER_NAME": "site",
        "FOUNDRY_PROJECT_URL": "https://demo-swe.services.ai.azure.com/api/projects/demo-swe-prj",
        "FOUNDRY_AGENT_NAME": "workshop-planner-demo", "FOUNDRY_AGENT_VERSION": args.agent_version,
    }
    env.update({name: {"name": name, "value": value} for name, value in values.items()})
    for name, ref in [("ENTRA_CLIENT_SECRET", "reader-secret"), ("SESSION_SECRET", "session-secret")]:
        env[name] = {"name": name, "secretRef": ref}
    arm(APP_ID, method="patch", body={"properties": {"template": {
        **properties["template"], "containers": [{
            **properties["template"]["containers"][0], "env": list(env.values()),
        }],
    }}})
    arm(APP_ID, action="/stop", method="post")
    arm(APP_ID, action="/start", method="post")
    wait_status(origin, "/api/config", 401)
    print(f"Reader configuration applied: {origin}. Interactive allowed/denied login still needs verification.")


if __name__ == "__main__":
    main()
