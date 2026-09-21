from __future__ import annotations

import copy
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import httpx

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts"


class _AzureCliCredential:
    def get_token(self, scope: str):
        return types.SimpleNamespace(token=f"token-for-{scope}")


azure_module = types.ModuleType("azure")
identity_module = types.ModuleType("azure.identity")
identity_module.AzureCliCredential = _AzureCliCredential
azure_module.identity = identity_module
sys.modules.setdefault("azure", azure_module)
sys.modules.setdefault("azure.identity", identity_module)

sys.path.insert(0, str(SCRIPT_DIR))
import configure_entra  # type: ignore  # noqa: E402


class FakeClient:
    def __init__(self, responses: list[httpx.Response]):
        self._responses = responses
        self.requests: list[dict[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def request(self, method: str, url: str, headers=None, json=None):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "json": json,
            }
        )
        if not self._responses:
            raise AssertionError(f"unexpected request {method} {url}")
        response = self._responses.pop(0)
        response.request = httpx.Request(method, url)
        return response


class ClientFactory:
    def __init__(self, responses: list[httpx.Response]):
        self.responses = responses
        self.instances: list[FakeClient] = []

    def __call__(self, timeout: float = 60.0):
        client = FakeClient(self.responses)
        self.instances.append(client)
        return client


class ConfigureEntraTests(unittest.TestCase):
    def setUp(self):
        self.graph_base = configure_entra.GRAPH_BASE
        self.arm_base = configure_entra.ARM_BASE

    def response(self, status: int = 200, *, json_data=None, headers=None, url: str = "https://example.test/"):
        content = b""
        if json_data is not None:
            content = json.dumps(json_data).encode()
        return httpx.Response(status, content=content, headers=headers or {}, request=httpx.Request("GET", url))

    def test_build_context_includes_all_dockerfile_copy_targets(self):
        dockerfile = (ROOT / "Dockerfile").read_text().splitlines()
        targets = []
        for line in dockerfile:
            stripped = line.strip()
            if stripped.startswith("COPY "):
                parts = stripped.split()
                self.assertGreaterEqual(len(parts), 3, stripped)
                targets.append(parts[1])
        self.assertEqual(sorted(set(targets)), ["app", "requirements.txt", "scripts", "static"])

        deploy = (SCRIPT_DIR / "deploy.sh").read_text()
        self.assertIn('cp "$ROOT_DIR/Dockerfile" "$BUILD_CONTEXT/Dockerfile"', deploy)
        self.assertIn('cp "$ROOT_DIR/requirements.txt" "$BUILD_CONTEXT/requirements.txt"', deploy)
        self.assertIn('cp -R "$ROOT_DIR/app" "$BUILD_CONTEXT/app"', deploy)
        self.assertIn('cp -R "$ROOT_DIR/scripts" "$BUILD_CONTEXT/scripts"', deploy)
        self.assertIn('cp -R "$ROOT_DIR/static" "$BUILD_CONTEXT/static"', deploy)
        self.assertIn('rm -f "$PLAN_FILE"', deploy)

    def test_azapi_v2_uses_dynamic_hcl_bodies_and_outputs(self):
        main_tf = (ROOT / "infra" / "main.tf").read_text()
        outputs_tf = (ROOT / "infra" / "outputs.tf").read_text()

        self.assertNotIn("body = jsonencode(", main_tf)
        self.assertNotIn("jsondecode(azapi_resource", outputs_tf)
        self.assertNotIn("azapi_resource.container_app[0].output", outputs_tf)

    def test_foundry_identity_role_supports_openai_and_mai_data_planes(self):
        main_tf = (ROOT / "infra" / "main.tf").read_text()

        self.assertIn('role_definition_name = "Cognitive Services User"', main_tf)
        self.assertNotIn('role_definition_name = "Cognitive Services OpenAI User"', main_tf)

    def test_terraform_preserves_application_managed_auth_configuration(self):
        main_tf = (ROOT / "infra" / "main.tf").read_text()

        self.assertNotIn("ENTRA_CLIENT_SECRET", main_tf)
        self.assertNotIn("SESSION_SECRET", main_tf)
        self.assertIn("Microsoft.Network/virtualNetworks/subnets/join/action", main_tf)

        deploy = (SCRIPT_DIR / "deploy.sh").read_text()
        self.assertIn('container_app_fqdn()', deploy)
        self.assertIn('current_container_image()', deploy)
        self.assertIn("image lookup failed; refusing a plan", deploy)
        self.assertIn("@sha256:[0-9a-f]{64}", deploy)
        self.assertIn('verify_local_state_ownership()', deploy)
        self.assertIn('load_current_auth_config()', deploy)
        self.assertIn('-target=azapi_resource.express_environment', deploy)
        self.assertIn('if [[ "$CONTAINER_APP_EXISTS" == "false" ]]', deploy)
        self.assertIn('--container-image "$BUILT_IMAGE"', deploy)
        self.assertIn("configure_args+=(--image-only)", deploy)
        self.assertIn("this checkout does not own it in Terraform state", deploy)
        self.assertIn("automatic recreation is disabled", deploy)
        self.assertIn('current_container_image >/dev/null', deploy)
        self.assertIn("key.lower() for key in bound", deploy)
        self.assertNotIn("output -raw container_app_origin", deploy)
        self.assertNotIn("output -raw container_app_fqdn", deploy)

    def test_graph_requests_send_bearer_headers(self):
        factory = ClientFactory([self.response(json_data={"value": []})])
        with patch.object(configure_entra, "access_token", return_value="supplied-token"), patch.object(
            configure_entra.httpx, "Client", side_effect=factory
        ):
            configure_entra.graph_request("GET", "/applications?$filter=displayName eq 'demo'")

        request = factory.instances[0].requests[0]
        self.assertEqual(request["headers"]["Authorization"], "Bearer supplied-token")
        self.assertNotIn("******", request["headers"]["Authorization"])

    def test_ensure_application_retries_on_precondition_failure(self):
        app_id = "app-1"
        etag = 'W/"etag-1"'
        current = {
            "id": app_id,
            "appId": "client-1",
            "web": {"redirectUris": ["https://old.example/oauth/entra/callback"]},
            "passwordCredentials": [],
            "@odata.etag": etag,
        }
        updated = {
            "id": app_id,
            "appId": "client-1",
            "web": {
                "redirectUris": [
                    "https://old.example/oauth/entra/callback",
                    "https://new.example/oauth/entra/callback",
                ]
            },
            "passwordCredentials": [],
        }
        factory = ClientFactory(
            [
                self.response(json_data={"value": [current]}, url=f"{self.graph_base}/applications"),
                self.response(412, url=f"{self.graph_base}/applications/{app_id}"),
                self.response(json_data={"value": [updated]}, url=f"{self.graph_base}/applications"),
            ]
        )
        with patch.object(configure_entra, "access_token", return_value="graph-token"), patch.object(
            configure_entra.httpx, "Client", side_effect=factory
        ):
            result = configure_entra.ensure_application("demo", "https://new.example/oauth/entra/callback")

        self.assertEqual(result["web"]["redirectUris"][-1], "https://new.example/oauth/entra/callback")
        patch_request = factory.instances[1].requests[0]
        self.assertEqual(patch_request["headers"]["Authorization"], "Bearer graph-token")
        self.assertEqual(patch_request["headers"]["If-Match"], etag)

    def test_container_app_update_removes_output_only_fields(self):
        configuration = {
            "activeRevisionsMode": "Single",
            "ingress": {"external": True, "fqdn": "demo.example"},
        }
        template = {
            "containers": [{"name": "web", "image": "example/image", "imageType": "ContainerImage"}],
            "initContainers": [{"name": "init", "image": "example/init", "imageType": "ContainerImage"}],
        }

        writable_configuration = configure_entra._writable_configuration(configuration)
        writable_template = configure_entra._writable_template(template)

        self.assertNotIn("fqdn", writable_configuration["ingress"])
        self.assertNotIn("imageType", writable_template["containers"][0])
        self.assertNotIn("imageType", writable_template["initContainers"][0])
        self.assertEqual(configuration["ingress"]["fqdn"], "demo.example")
        self.assertEqual(template["containers"][0]["imageType"], "ContainerImage")

    def test_container_app_update_creates_session_secret_and_preserves_existing_client_secret(self):
        current = {
            "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/containerApps/demo",
            "location": "swedencentral",
            "tags": {},
            "identity": {"type": "UserAssigned", "userAssignedIdentities": {"/ids/uami": {}}},
            "properties": {
                "managedEnvironmentId": "/env/1",
                "configuration": {
                    "secrets": [
                        {"name": "existing-client-secret"},
                        {"name": f"{configure_entra.PASSWORD_LABEL}-old", "value": "old-value"},
                    ],
                    "registries": [],
                },
                "template": {
                    "containers": [{"name": "web", "env": []}],
                    "scale": {"minReplicas": 0, "maxReplicas": 1, "rules": []},
                },
            },
        }
        updated = copy.deepcopy(current)
        factory = ClientFactory(
            [
                self.response(json_data=current),
                self.response(json_data=updated),
            ]
        )
        with patch.object(configure_entra, "access_token", return_value="arm-token"), patch.object(
            configure_entra.httpx, "Client", side_effect=factory
        ):
            configure_entra._update_container_app(
                current["id"],
                origin="https://new.example",
                app_client_id="client-1",
                identity_client_id="identity-1",
                tenant_id="tenant-1",
                secret_name="existing-client-secret",
                secret_value=None,
                session_secret_value="session-value",
                container_image="example.azurecr.io/demo@sha256:new",
                snapshot=current,
            )

        update_payload = factory.instances[1].requests[0]["json"]
        secrets_payload = update_payload["properties"]["configuration"]["secrets"]
        self.assertEqual(
            update_payload["properties"]["template"]["containers"][0]["image"],
            "example.azurecr.io/demo@sha256:new",
        )
        self.assertIn({"name": "existing-client-secret"}, secrets_payload)
        self.assertNotIn(
            {"name": f"{configure_entra.PASSWORD_LABEL}-old", "value": "old-value"},
            secrets_payload,
        )
        self.assertIn(
            {"name": configure_entra.SESSION_SECRET_LABEL, "value": "session-value"},
            secrets_payload,
        )

    def test_container_app_secret_hydration_keeps_values_in_memory(self):
        snapshot = {
            "properties": {
                "configuration": {
                    "secrets": [
                        {"name": "client-secret"},
                        {"name": configure_entra.SESSION_SECRET_LABEL},
                    ]
                }
            }
        }

        configure_entra._hydrate_container_app_secrets(
            snapshot,
            {
                "client-secret": "client-value",
                configure_entra.SESSION_SECRET_LABEL: "session-value",
            },
        )

        self.assertEqual(
            snapshot["properties"]["configuration"]["secrets"],
            [
                {"name": "client-secret", "value": "client-value"},
                {"name": configure_entra.SESSION_SECRET_LABEL, "value": "session-value"},
            ],
        )
        self.assertEqual(
            configure_entra._snapshot_secret_values(snapshot),
            {
                "client-secret": "client-value",
                configure_entra.SESSION_SECRET_LABEL: "session-value",
            },
        )

    def test_update_container_app_retries_on_precondition_failure(self):
        app_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/containerApps/demo"
        etag = 'W/"etag-2"'
        current = {
            "id": app_id,
            "location": "swedencentral",
            "tags": {},
            "identity": {"type": "UserAssigned", "userAssignedIdentities": {"/ids/uami": {}}},
            "properties": {
                "managedEnvironmentId": "/env/1",
                "configuration": {"secrets": [], "registries": []},
                "template": {
                    "containers": [{"name": "app", "env": []}],
                    "scale": {"minReplicas": 0, "maxReplicas": 1, "rules": []},
                },
            },
            "@odata.etag": etag,
        }
        updated = dict(current)
        updated = {
            **current,
            "properties": {
                **current["properties"],
                "configuration": {"secrets": [{"name": "secret-1", "value": "value-1"}], "registries": []},
                "template": {
                    **current["properties"]["template"],
                    "containers": [
                        {
                            "name": "app",
                            "env": [
                                {"name": "AUTH_ENABLED", "value": "true"},
                                {"name": "AUTH_PROVIDER", "value": "entra"},
                                {"name": "ENTRA_CLIENT_ID", "value": "client-1"},
                                {"name": "ENTRA_CLIENT_SECRET", "secretRef": "secret-1"},
                                {"name": "ENTRA_TENANT_ID", "value": "tenant-1"},
                                {"name": "PUBLIC_BASE_URL", "value": "https://new.example"},
                                {"name": "SESSION_SECRET", "secretRef": configure_entra.SESSION_SECRET_LABEL},
                            ],
                        }
                    ],
                },
            },
        }
        factory = ClientFactory(
            [
                self.response(json_data=current, url=f"{self.arm_base}{app_id}?api-version={configure_entra.ARM_API_VERSION}"),
                self.response(412, url=f"{self.arm_base}{app_id}?api-version={configure_entra.ARM_API_VERSION}"),
                self.response(json_data=current, url=f"{self.arm_base}{app_id}?api-version={configure_entra.ARM_API_VERSION}"),
                self.response(json_data=updated, url=f"{self.arm_base}{app_id}?api-version={configure_entra.ARM_API_VERSION}"),
            ]
        )
        with patch.object(configure_entra, "access_token", return_value="arm-token"), patch.object(
            configure_entra.httpx, "Client", side_effect=factory
        ):
            result = configure_entra._update_container_app(
                app_id,
                origin="https://new.example",
                app_client_id="client-1",
                identity_client_id="identity-1",
                tenant_id="tenant-1",
                secret_name="secret-1",
                secret_value="value-1",
                snapshot=current,
            )

        self.assertEqual(result["id"], app_id)
        put_request = factory.instances[1].requests[0]
        self.assertEqual(put_request["headers"]["Authorization"], "Bearer arm-token")
        self.assertEqual(put_request["headers"]["If-Match"], etag)

    def test_wait_for_container_app_provisioning_handles_async_update(self):
        in_progress = {"properties": {"provisioningState": "InProgress"}}
        succeeded = {"properties": {"provisioningState": "Succeeded"}}

        with patch.object(
            configure_entra,
            "_arm_json",
            side_effect=[in_progress, succeeded],
        ), patch.object(configure_entra.time, "sleep") as sleep_mock:
            result = configure_entra.wait_for_container_app_provisioning(
                "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/containerApps/demo",
                timeout_seconds=30,
            )

        self.assertEqual(result, succeeded)
        sleep_mock.assert_called_once_with(5)

    def test_image_only_update_skips_graph_and_preserves_auth_path(self):
        container_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/containerApps/demo"
        initial_app = {
            "id": container_id,
            "location": "swedencentral",
            "tags": {},
            "identity": {"type": "UserAssigned", "userAssignedIdentities": {"/ids/uami": {}}},
            "properties": {
                "managedEnvironmentId": "/env/1",
                "configuration": {"secrets": [{"name": "auth-secret", "value": "secret-value"}]},
                "template": {
                    "containers": [{"name": "app", "image": "old@sha256:digest", "env": []}],
                    "scale": {"minReplicas": 0, "maxReplicas": 1, "rules": []},
                },
            },
        }
        with patch.object(configure_entra, "ensure_application") as graph_mock, patch.object(
            configure_entra, "wait_for_container_app_provisioning", return_value=initial_app
        ), patch.object(configure_entra, "_arm_json", return_value=initial_app), patch.object(
            configure_entra, "_container_app_secret_values", return_value={"auth-secret": "secret-value"}
        ), patch.object(configure_entra, "_update_container_image", return_value=initial_app) as update_mock, patch.object(
            configure_entra, "stop_start_container_app"
        ), patch.object(configure_entra, "wait_for_health"), patch.object(
            configure_entra, "verify_auth_redirect"
        ):
            result = configure_entra.main([
                "--display-name",
                "demo",
                "--container-app-id",
                container_id,
                "--origin",
                "https://new.example",
                "--tenant-id",
                "tenant-1",
                "--identity-client-id",
                "identity-1",
                "--container-image",
                "new@sha256:digest",
                "--image-only",
            ])

        self.assertEqual(result, 0)
        graph_mock.assert_not_called()
        update_mock.assert_called_once()

    def test_failure_rolls_back_new_graph_secret_and_allows_rerun(self):
        app_id = "app-1"
        container_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/containerApps/demo"
        initial_app = {
            "id": container_id,
            "location": "swedencentral",
            "tags": {},
            "identity": {"type": "UserAssigned", "userAssignedIdentities": {"/ids/uami": {}}},
            "properties": {
                "managedEnvironmentId": "/env/1",
                "configuration": {"secrets": []},
                "template": {
                    "containers": [{"name": "app", "env": []}],
                    "scale": {"minReplicas": 0, "maxReplicas": 1, "rules": []},
                },
            },
        }
        app = {
            "id": app_id,
            "appId": "client-1",
            "web": {"redirectUris": []},
            "passwordCredentials": [],
        }
        with patch.object(configure_entra, "ensure_application", return_value=app), patch.object(
            configure_entra, "ensure_service_principal", return_value={"id": "sp-1", "appId": app["appId"]}
        ), patch.object(configure_entra, "_arm_json", return_value=initial_app), patch.object(
            configure_entra, "_container_app_secret_values", return_value={}
        ), patch.object(
            configure_entra, "create_client_secret", side_effect=[("first-secret", "first-key", "2030-01-01T00:00:00Z"), ("second-secret", "second-key", "2031-01-01T00:00:00Z")]
        ), patch.object(configure_entra, "_update_container_app", side_effect=[RuntimeError("boom"), initial_app]), patch.object(
            configure_entra, "stop_start_container_app"
        ), patch.object(configure_entra, "wait_for_container_app_provisioning"), patch.object(
            configure_entra, "wait_for_health"
        ), patch.object(configure_entra, "verify_auth_redirect"), patch.object(
            configure_entra, "_apply_container_app_snapshot"
        ) as restore_mock, patch.object(configure_entra, "remove_client_secret") as remove_mock, patch.object(
            configure_entra, "_delete_superseded_passwords"
        ):
            with self.assertRaises(RuntimeError):
                configure_entra.main([
                    "--display-name",
                    "demo",
                    "--container-app-id",
                    container_id,
                    "--origin",
                    "https://new.example",
                    "--tenant-id",
                    "tenant-1",
                    "--identity-client-id",
                    "identity-1",
                ])
            self.assertEqual(restore_mock.call_count, 1)
            remove_mock.assert_called_once_with(app_id, "first-key")

            result = configure_entra.main([
                "--display-name",
                "demo",
                "--container-app-id",
                container_id,
                "--origin",
                "https://new.example",
                "--tenant-id",
                "tenant-1",
                "--identity-client-id",
                "identity-1",
            ])
            self.assertEqual(result, 0)

    def test_failure_cleanup_still_deletes_secret_when_restore_fails(self):
        app_id = "app-1"
        container_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/containerApps/demo"
        initial_app = {
            "id": container_id,
            "location": "swedencentral",
            "tags": {},
            "identity": {"type": "UserAssigned", "userAssignedIdentities": {"/ids/uami": {}}},
            "properties": {
                "managedEnvironmentId": "/env/1",
                "configuration": {"secrets": []},
                "template": {
                    "containers": [{"name": "app", "env": []}],
                    "scale": {"minReplicas": 0, "maxReplicas": 1, "rules": []},
                },
            },
        }
        app = {
            "id": app_id,
            "appId": "client-1",
            "web": {"redirectUris": []},
            "passwordCredentials": [],
        }
        with patch.object(configure_entra, "ensure_application", return_value=app), patch.object(
            configure_entra, "ensure_service_principal", return_value={"id": "sp-1", "appId": app["appId"]}
        ), patch.object(configure_entra, "_arm_json", return_value=initial_app), patch.object(
            configure_entra, "_container_app_secret_values", return_value={}
        ), patch.object(
            configure_entra, "create_client_secret", return_value=("new-secret", "new-key", "2030-01-01T00:00:00Z")
        ), patch.object(configure_entra, "_update_container_app", side_effect=RuntimeError("boom")), patch.object(
            configure_entra, "stop_start_container_app"
        ), patch.object(configure_entra, "wait_for_container_app_provisioning"), patch.object(
            configure_entra, "wait_for_health"
        ), patch.object(configure_entra, "verify_auth_redirect"), patch.object(
            configure_entra, "_apply_container_app_snapshot", side_effect=RuntimeError("restore failed")
        ) as restore_mock, patch.object(configure_entra, "remove_client_secret") as remove_mock, patch.object(
            configure_entra, "_delete_superseded_passwords"
        ):
            with self.assertRaises(RuntimeError):
                configure_entra.main([
                    "--display-name",
                    "demo",
                    "--container-app-id",
                    container_id,
                    "--origin",
                    "https://new.example",
                    "--tenant-id",
                    "tenant-1",
                    "--identity-client-id",
                    "identity-1",
                ])

        self.assertEqual(restore_mock.call_count, 1)
        remove_mock.assert_called_once_with(app_id, "new-key")

    def test_successful_rotation_cleans_up_old_password_after_health(self):
        app_id = "app-1"
        container_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/containerApps/demo"
        initial_app = {
            "id": container_id,
            "location": "swedencentral",
            "tags": {},
            "identity": {"type": "UserAssigned", "userAssignedIdentities": {"/ids/uami": {}}},
            "properties": {
                "managedEnvironmentId": "/env/1",
                "configuration": {
                    "secrets": [{"name": "foundry-image-models-auth-old", "value": "old-secret"}],
                },
                "template": {
                    "containers": [
                        {
                            "name": "app",
                            "env": [{"name": "ENTRA_CLIENT_SECRET", "secretRef": "foundry-image-models-auth-old"}],
                        }
                    ],
                    "scale": {"minReplicas": 0, "maxReplicas": 1, "rules": []},
                },
            },
        }
        app = {
            "id": app_id,
            "appId": "client-1",
            "web": {"redirectUris": ["https://new.example/oauth/entra/callback"]},
            "passwordCredentials": [{"keyId": "old-key", "displayName": configure_entra.PASSWORD_LABEL}],
        }
        order = MagicMock()
        with patch.object(configure_entra, "ensure_application", return_value=app), patch.object(
            configure_entra, "ensure_service_principal", return_value={"id": "sp-1", "appId": app["appId"]}
        ), patch.object(configure_entra, "_arm_json", return_value=initial_app), patch.object(
            configure_entra, "_container_app_secret_values", return_value={}
        ), patch.object(
            configure_entra, "create_client_secret", return_value=("new-secret", "new-key", "2030-01-01T00:00:00Z")
        ), patch.object(configure_entra, "_update_container_app", return_value=initial_app), patch.object(
            configure_entra, "stop_start_container_app"
        ), patch.object(configure_entra, "wait_for_container_app_provisioning"), patch.object(
            configure_entra, "wait_for_health", side_effect=lambda origin: order.mock_calls.append(call.wait(origin))
        ), patch.object(
            configure_entra, "verify_auth_redirect", side_effect=lambda origin: order.mock_calls.append(call.redirect(origin))
        ), patch.object(configure_entra, "_delete_superseded_passwords", side_effect=lambda app_id_arg, keep_key_id: order.mock_calls.append(call.delete(app_id_arg, keep_key_id))):
            result = configure_entra.main([
                "--display-name",
                "demo",
                "--container-app-id",
                container_id,
                "--origin",
                "https://new.example",
                "--tenant-id",
                "tenant-1",
                "--identity-client-id",
                "identity-1",
                "--rotate-client-secret",
            ])

        self.assertEqual(result, 0)
        self.assertEqual(order.mock_calls, [call.wait("https://new.example"), call.redirect("https://new.example"), call.delete(app_id, "new-key")])

    def test_drift_recovery_cleans_up_superseded_passwords_without_rotate_flag(self):
        app_id = "app-1"
        container_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/containerApps/demo"
        initial_app = {
            "id": container_id,
            "location": "swedencentral",
            "tags": {},
            "identity": {"type": "UserAssigned", "userAssignedIdentities": {"/ids/uami": {}}},
            "properties": {
                "managedEnvironmentId": "/env/1",
                "configuration": {"secrets": [{"name": "foundry-image-models-auth-old", "value": "old-secret"}]},
                "template": {
                    "containers": [{"name": "app", "env": []}],
                    "scale": {"minReplicas": 0, "maxReplicas": 1, "rules": []},
                },
            },
        }
        app = {
            "id": app_id,
            "appId": "client-1",
            "web": {"redirectUris": ["https://new.example/oauth/entra/callback"]},
            "passwordCredentials": [{"keyId": "old-key", "displayName": configure_entra.PASSWORD_LABEL}],
        }
        calls: list[tuple[str, str]] = []
        with patch.object(configure_entra, "ensure_application", return_value=app), patch.object(
            configure_entra, "ensure_service_principal", return_value={"id": "sp-1", "appId": app["appId"]}
        ), patch.object(configure_entra, "_arm_json", return_value=initial_app), patch.object(
            configure_entra, "_container_app_secret_values", return_value={}
        ), patch.object(
            configure_entra, "create_client_secret", return_value=("new-secret", "new-key", "2030-01-01T00:00:00Z")
        ), patch.object(configure_entra, "_update_container_app", return_value=initial_app), patch.object(
            configure_entra, "stop_start_container_app"
        ), patch.object(configure_entra, "wait_for_container_app_provisioning"), patch.object(
            configure_entra, "wait_for_health"
        ), patch.object(configure_entra, "verify_auth_redirect"), patch.object(
            configure_entra, "_delete_superseded_passwords", side_effect=lambda app_id_arg, keep_key_id: calls.append((app_id_arg, keep_key_id))
        ):
            result = configure_entra.main([
                "--display-name",
                "demo",
                "--container-app-id",
                container_id,
                "--origin",
                "https://new.example",
                "--tenant-id",
                "tenant-1",
                "--identity-client-id",
                "identity-1",
            ])

        self.assertEqual(result, 0)
        self.assertEqual(calls, [(app_id, "new-key")])


if __name__ == "__main__":
    unittest.main()
