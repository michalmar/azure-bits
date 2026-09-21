from __future__ import annotations

import asyncio
import base64
import json

import pytest

from app.config import ALLOWED_MODELS
from tests.backend.helpers import make_client, make_service


PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake-png").decode("ascii")


def _response(data):
    return {"data": [{"b64_json": data}], "size": "1024x1024", "quality": "standard"}


def test_models_route_uses_management_scope_and_returns_all_models():
    def responder(request):
        assert request.method == "GET"
        assert "management.azure.com" in str(request.url)
        payload = {
            "value": [
                {"name": "gpt-image-2.5-sunburst", "capabilities": {"imageEdits": True}},
                {"name": "MAI-Image-2.6-Flash", "capabilities": {"imageEdits": False}},
                {"name": "MAI-Image-2.6", "capabilities": {"imageEdits": True}},
                {"name": "MAI-Image-2.5", "capabilities": {"imageEdits": True}},
                {"name": "gpt-image-2", "capabilities": {"imageEdits": False}},
            ]
        }
        return httpx.Response(200, json=payload)

    import httpx

    service, cred = make_service(responder)
    with make_client(service) as client:
        response = client.get("/api/models")

    assert response.status_code == 200
    data = response.json()
    assert [model["name"] for model in data["models"]] == list(ALLOWED_MODELS)
    assert data["models"][0]["capabilities"]["imageEdits"]["status"] == "ready"
    assert data["models"][1]["capabilities"]["imageEdits"]["status"] == "unsupported"
    assert cred.scopes == ["https://management.azure.com/.default"]


def test_management_capabilities_accept_string_booleans():
    import httpx

    def responder(request):
        return httpx.Response(
            200,
            json={
                "value": [
                    {"name": "gpt-image-2", "capabilities": {"imageEdits": "true"}},
                    {"name": "MAI-Image-2.5", "capabilities": {"imageEdits": "false"}},
                ]
            },
        )

    service, _ = make_service(responder)
    parsed = asyncio.run(service.model_capabilities(refresh=True))

    assert parsed["gpt-image-2"].status == "ready"
    assert parsed["gpt-image-2"].image_edits is True
    assert parsed["MAI-Image-2.5"].status == "unsupported"
    assert parsed["MAI-Image-2.5"].image_edits is False


@pytest.mark.parametrize(
    "model,expected_path,expected_body",
    [
        (
            "MAI-Image-2.6",
            "/mai/v1/images/generations",
            {"model": "MAI-Image-2.6", "prompt": "precise prompt"},
        ),
        (
            "gpt-image-2.5-sunburst",
            "/openai/deployments/gpt-image-2.5-sunburst/images/generations",
            {"prompt": "precise prompt"},
        ),
    ],
)
def test_prompt_only_generation_selects_route_and_leaves_out_optional_settings(model, expected_path, expected_body):
    captured = {}

    def responder(request):
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(200, json=_response(PNG_B64))

    import httpx

    service, _ = make_service(responder)
    with make_client(service) as client:
        response = client.post(
            "/api/generate",
            files=[("model", (None, model)), ("prompt", (None, "precise prompt"))],
        )

    assert response.status_code == 200
    assert expected_path in captured["url"]
    assert json.loads(captured["body"]) == expected_body
    assert "size" not in captured["body"]
    assert "quality" not in captured["body"]
    assert response.json()["mimeType"] == "image/png"


def test_image_generation_checks_capabilities_before_edit_route():
    requests = []
    edit_body = {}

    def responder(request):
        body = request.content.decode("utf-8", errors="ignore")
        requests.append((request.method, str(request.url)))
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"value": [{"name": "gpt-image-2.5-sunburst", "capabilities": {"imageEdits": True}}]})
        edit_body["body"] = body
        return httpx.Response(200, json=_response(PNG_B64))

    import httpx

    service, _ = make_service(responder)
    with make_client(service) as client:
        response = client.post(
            "/api/generate",
            files=[
                ("model", (None, "gpt-image-2.5-sunburst")),
                ("prompt", (None, "edit prompt")),
                ("image", ("sample.png", b"\x89PNG\r\n\x1a\nabc", "image/png")),
            ],
        )

    assert response.status_code == 200
    assert any(url.endswith("/models?api-version=2025-06-01") for _, url in requests)
    assert any("/images/edits" in url for _, url in requests)
    assert "size" not in edit_body["body"]
    assert "quality" not in edit_body["body"]
    assert 'name="prompt"' in edit_body["body"]
    assert 'name="image"' in edit_body["body"]


def test_capability_failures_surface_explicitly_and_block_image_generation():
    def responder(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(500, json={"error": "boom"})
        raise AssertionError("generation should not run when capability lookup fails")

    import httpx

    service, _ = make_service(responder)
    with make_client(service) as client:
        response = client.post(
            "/api/generate",
            files=[
                ("model", (None, "gpt-image-2.5-sunburst")),
                ("prompt", (None, "edit prompt")),
                ("image", ("sample.png", b"\x89PNG\r\n\x1a\nabc", "image/png")),
            ],
        )

    assert response.status_code == 503
    assert "capability lookup failed" in response.json()["detail"]


@pytest.mark.parametrize(
    "content_type,body,status",
    [
        ("text/plain", b"not an image", 415),
        ("image/png", b"\x89PNG\r\n\x1a\n" + b"x" * 900001, 413),
    ],
)
def test_upload_validation_rejects_bad_types_and_oversized_images(content_type, body, status):
    def responder(request):
        raise AssertionError("generation should not run for invalid uploads")

    service, _ = make_service(responder)
    with make_client(service) as client:
        response = client.post(
            "/api/generate",
            files=[
                ("model", (None, "gpt-image-2.5-sunburst")),
                ("prompt", (None, "upload prompt")),
                ("image", ("upload.bin", body, content_type)),
            ],
        )

    assert response.status_code == status


def test_generate_route_does_not_write_to_disk(monkeypatch):
    writes = []

    def fail_write(self, *args, **kwargs):
        writes.append(str(self))
        raise AssertionError("unexpected filesystem write")

    monkeypatch.setattr("pathlib.Path.write_bytes", fail_write)
    monkeypatch.setattr("pathlib.Path.write_text", fail_write)

    def responder(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"value": [{"name": "gpt-image-2.5-sunburst", "capabilities": {"imageEdits": True}}]})
        return httpx.Response(200, json=_response(PNG_B64))

    import httpx

    service, _ = make_service(responder)
    with make_client(service) as client:
        response = client.post(
            "/api/generate",
            files=[
                ("model", (None, "gpt-image-2.5-sunburst")),
                ("prompt", (None, "memory only")),
                ("image", ("sample.png", b"\x89PNG\r\n\x1a\nabc", "image/png")),
            ],
        )

    assert response.status_code == 200
    assert writes == []


def test_rate_limit_preserves_retry_after_header():
    def responder(request):
        if request.url.path.endswith("/openai/deployments/gpt-image-2.5-sunburst/images/generations"):
            return httpx.Response(429, headers={"Retry-After": "17"}, json={"error": "rate limited"})
        raise AssertionError("unexpected request")

    import httpx

    service, _ = make_service(responder)
    with make_client(service) as client:
        response = client.post(
            "/api/generate",
            files=[
                ("model", (None, "gpt-image-2.5-sunburst")),
                ("prompt", (None, "rate limit prompt")),
            ],
        )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "17"


def test_capability_failure_keeps_last_good_snapshot():
    import httpx

    responses = iter(
        [
            httpx.Response(
                200,
                json={
                    "value": [
                        {"name": "gpt-image-2.5-sunburst", "capabilities": {"imageEdits": True}},
                        {"name": "MAI-Image-2.6-Flash", "capabilities": {"imageEdits": False}},
                        {"name": "MAI-Image-2.6", "capabilities": {"imageEdits": True}},
                        {"name": "MAI-Image-2.5", "capabilities": {"imageEdits": True}},
                        {"name": "gpt-image-2", "capabilities": {"imageEdits": False}},
                    ]
                },
            ),
            httpx.Response(500, json={"error": "boom"}),
        ]
    )

    def responder(request):
        if request.url.path.endswith("/models"):
            return next(responses)
        raise AssertionError("unexpected request")

    service, _ = make_service(responder)
    async def run():
        first = await service.model_capabilities()
        second = await service.model_capabilities(refresh=True)
        return first, second

    first, second = asyncio.run(run())

    assert first["gpt-image-2.5-sunburst"].status == "ready"
    assert second["gpt-image-2.5-sunburst"].status == "error"
    assert second["gpt-image-2.5-sunburst"].stale is True
    assert second["gpt-image-2.5-sunburst"].last_known["status"] == "ready"

    with make_client(service) as client:
        response = client.post(
            "/api/generate",
            files=[
                ("model", (None, "gpt-image-2.5-sunburst")),
                ("prompt", (None, "edit prompt")),
                ("image", ("sample.png", b"\x89PNG\r\n\x1a\nabc", "image/png")),
            ],
        )

    assert response.status_code == 503


def test_bounded_upload_parsing_avoids_disk_and_hard_caps(monkeypatch):
    import tempfile

    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("disk spool not allowed")))
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("named temp not allowed")))
    monkeypatch.setattr(tempfile, "TemporaryFile", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("temporary file not allowed")))
    monkeypatch.setattr("pathlib.Path.write_bytes", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("filesystem write not allowed")))

    def responder(request):
        if request.url.path.endswith("/openai/deployments/gpt-image-2.5-sunburst/images/edits"):
            return httpx.Response(200, json=_response(PNG_B64))
        raise AssertionError("unexpected request")

    import httpx

    service, _ = make_service(responder)
    image_payload = b"\x89PNG\r\n\x1a\n" + b"x" * (900001 - 8)
    with make_client(service) as client:
        response = client.post(
            "/api/generate",
            content=(
                b"--boundary\r\n"
                b'Content-Disposition: form-data; name="model"\r\n\r\n'
                b"gpt-image-2.5-sunburst\r\n"
                b"--boundary\r\n"
                b'Content-Disposition: form-data; name="prompt"\r\n\r\n'
                b"bounded upload\r\n"
                b"--boundary\r\n"
                b'Content-Disposition: form-data; name="image"; filename="sample.png"\r\n'
                b"Content-Type: image/png\r\n\r\n"
                + image_payload
                + b"\r\n--boundary--\r\n"
            ),
            headers={
                "content-type": "multipart/form-data; boundary=boundary",
                "content-length": str(len(
                    b"--boundary\r\n"
                    b'Content-Disposition: form-data; name="model"\r\n\r\n'
                    b"gpt-image-2.5-sunburst\r\n"
                    b"--boundary\r\n"
                    b'Content-Disposition: form-data; name="prompt"\r\n\r\n'
                    b"bounded upload\r\n"
                    b"--boundary\r\n"
                    b'Content-Disposition: form-data; name="image"; filename="sample.png"\r\n'
                    b"Content-Type: image/png\r\n\r\n"
                    + image_payload
                    + b"\r\n--boundary--\r\n"
                )),
            },
        )

    assert response.status_code == 413
