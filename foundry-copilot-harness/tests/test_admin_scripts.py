import importlib.util
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_script(name, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reader_configuration_preserves_callbacks_and_secret_references(monkeypatch, capsys):
    module = load_script("configure-app", monkeypatch)
    monkeypatch.setattr("sys.argv", ["configure-app.py", "--approve-reader-changes", "--agent-version", "1"])
    source = {"properties": {"template": {"containers": [{"env": [
        {"name": "AUTH_PROVIDER", "value": "entra"},
        {"name": "ALLOWED_USERS", "value": "entra:test-reader"},
        {"name": "ENTRA_CLIENT_ID", "value": "test-client"},
        {"name": "ENTRA_TENANT_ID", "value": "test-tenant"},
        {"name": "ENTRA_CLIENT_SECRET", "secretRef": "existing-secret"},
    ]}]}}}
    target = {"properties": {
        "configuration": {"ingress": {"fqdn": "demo.example"}},
        "template": {"containers": [{"image": "preserved", "env": []}]},
    }}
    operations, updates = [], []

    def arm(identifier, **kwargs):
        operations.append((identifier, kwargs))
        if kwargs.get("action") == "/listSecrets":
            return {"value": [{"name": "existing-secret", "value": "test-only-reader-credential"}]}
        return source if identifier == module.SOURCE_APP_ID else target

    def az(*args):
        operations.append(("az", args))
        if args[:3] == ("ad", "app", "show"):
            return {"id": "test-registration", "web": {"redirectUris": ["https://existing.example/callback"]}}

    monkeypatch.setattr(module, "arm", arm)
    monkeypatch.setattr(module, "az", az)
    monkeypatch.setattr(module, "update_app", lambda **kwargs: updates.append(kwargs))
    monkeypatch.setattr(module, "wait_status", lambda *args: None)
    module.main()
    callback_update = next(args for name, args in operations if name == "az" and args[:3] == ("ad", "app", "update"))
    assert callback_update[-2:] == ("https://existing.example/callback", "https://demo.example/oauth/entra/callback")
    assert updates[0]["secrets"]["reader-secret"] == "test-only-reader-credential"
    patch = next(kwargs["body"] for _, kwargs in operations if isinstance(kwargs, dict) and kwargs.get("method") == "patch")
    container = patch["properties"]["template"]["containers"][0]
    assert container["image"] == "preserved"
    assert {"name": "ENTRA_CLIENT_SECRET", "secretRef": "reader-secret"} in container["env"]
    assert "test-only-reader-credential" not in repr(patch)
    assert "test-only-reader-credential" not in capsys.readouterr().out


def test_lockdown_revokes_exact_role_even_if_app_verification_fails(monkeypatch, tmp_path):
    module = load_script("publish-assets", monkeypatch)
    module.MARKER = tmp_path / "recovery.json"
    module.MARKER.write_text("recovery evidence")
    calls = []
    monkeypatch.setattr(module, "update_app", lambda **kwargs: "https://demo.example")

    def fail(*args, **kwargs):
        raise RuntimeError("Expected 404 but app did not restart")

    monkeypatch.setattr(module, "wait_status", fail)
    monkeypatch.setattr(module, "az", lambda *args: calls.append(args))
    with pytest.raises(RuntimeError, match="Expected 404"):
        module.lockdown("exact-role-id")
    assert calls == [("role", "assignment", "delete", "--ids", "exact-role-id")]
    assert module.MARKER.exists()


def test_lockdown_checks_all_management_methods(monkeypatch, tmp_path):
    module = load_script("publish-assets", monkeypatch)
    module.MARKER = tmp_path / "recovery.json"
    module.MARKER.write_text("recovery evidence")
    checks = []
    monkeypatch.setattr(module, "update_app", lambda **kwargs: "https://demo.example")
    monkeypatch.setattr(module, "az", lambda *args: None)
    monkeypatch.setattr(module, "wait_status", lambda *args, **kwargs: checks.append((args, kwargs)))
    module.lockdown("exact-role-id")
    assert [kwargs.get("method", "GET") for _, kwargs in checks] == ["GET", "HEAD", "PUT", "DELETE", "GET"]
    assert all(args[2] == 404 for args, _ in checks)
    assert not module.MARKER.exists()


def test_wait_status_tolerates_restart_without_following_redirects(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import cloud

    attempts = iter([httpx.ConnectError("restarting"), SimpleNamespace(status_code=404)])
    calls = []

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(cloud.httpx, "request", request)
    monkeypatch.setattr(cloud.time, "sleep", lambda _: None)
    cloud.wait_status("https://demo.example", "/_publish/blobs/file", 404, method="DELETE", attempts=2)
    assert len(calls) == 2
    assert calls[0][0][0] == "DELETE"
    assert calls[0][1]["follow_redirects"] is False


def test_first_secret_configuration_accepts_azure_null_secrets(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import cloud

    app = {"properties": {
        "configuration": {"secrets": None, "ingress": {"fqdn": "demo.example"}},
        "template": {"containers": [{"image": "preserved", "env": []}], "scale": {"maxReplicas": 1}},
    }}
    calls = []

    def arm(identifier, **kwargs):
        calls.append(kwargs)
        return app

    monkeypatch.setattr(cloud, "arm", arm)
    assert cloud.update_app(secrets={"reader-secret": "test-only-secret"}) == "https://demo.example"
    configuration = calls[1]["body"]["properties"]["configuration"]
    assert configuration["secrets"] == [{"name": "reader-secret", "value": "test-only-secret"}]
    assert calls[1]["body"]["properties"]["template"]["scale"] == {"maxReplicas": 1}
    assert [call.get("action") for call in calls[2:]] == ["/stop", "/start"]


def test_runtime_updates_preserve_secret_values_only_in_memory(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import cloud

    app = {"properties": {
        "configuration": {
            "secrets": [{"name": "reader-secret"}], "ingress": {"fqdn": "demo.example"},
        },
        "template": {"containers": [{"image": "preserved", "env": [{"name": "ENTRA_CLIENT_SECRET", "secretRef": "reader-secret"}]}]},
    }}
    calls = []

    def arm(identifier, **kwargs):
        calls.append(kwargs)
        if kwargs.get("action") == "/listSecrets":
            return {"value": [{"name": "reader-secret", "value": "test-only-preserved-secret"}]}
        return app

    monkeypatch.setattr(cloud, "arm", arm)
    cloud.update_app(values={"UPLOAD_API_ENABLED": "false"})
    patch = next(call["body"] for call in calls if call.get("method") == "patch")
    assert patch["properties"]["configuration"]["secrets"] == [
        {"name": "reader-secret", "value": "test-only-preserved-secret"},
    ]
    assert app["properties"]["configuration"]["secrets"] == [{"name": "reader-secret"}]
    assert {"name": "ENTRA_CLIENT_SECRET", "secretRef": "reader-secret"} in patch["properties"]["template"]["containers"][0]["env"]
