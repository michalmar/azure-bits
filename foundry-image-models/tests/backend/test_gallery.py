from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from app.prompts import GALLERY_PROMPTS
from app.service import FoundryService
from tests.backend.helpers import make_client


def test_gallery_endpoint_returns_generation_guidance_when_manifest_missing(monkeypatch, tmp_path):
    service = FoundryService(credential=object())
    monkeypatch.setattr(service, "gallery_manifest_path", lambda: tmp_path / "missing-manifest.json")

    with make_client(service) as client:
        response = client.get("/api/gallery")

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"] == []
    assert payload["prompts"] == list(GALLERY_PROMPTS)
    assert "generationGuidance" in payload


def test_gallery_generator_resumes_from_manifest_and_existing_files(monkeypatch):
    from scripts import generate_gallery

    scratch = Path("tests/backend/.gallery-resume")
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        monkeypatch.setattr(generate_gallery, "OUTPUT_DIR", scratch)
        monkeypatch.setattr(generate_gallery, "MANIFEST_PATH", scratch / "manifest.json")
        monkeypatch.setattr(
            generate_gallery,
            "GALLERY_PROMPTS",
            (
                {"id": "p1", "label": "Prompt 1", "prompt": "prompt one"},
                {"id": "p2", "label": "Prompt 2", "prompt": "prompt two"},
            ),
        )
        monkeypatch.setattr(generate_gallery, "ALLOWED_MODELS", ("m1", "m2"))

        class FakeCredential:
            def get_token(self, scope: str):
                return type("Token", (), {"token": "t"})()

        class FakeService:
            def __init__(self):
                self.calls = 0

            async def generate_image(self, *, model: str, prompt: str, image=None, image_filename=None, image_content_type=None):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("temporary generation failure")
                return type(
                    "Result",
                    (),
                    {
                        "data_url": "data:image/png;base64,cG5n",
                        "metadata": {"size": "1x1"},
                    },
                )()

            async def close(self):
                return None

        first_service = FakeService()

        monkeypatch.setattr(generate_gallery, "AzureCliCredential", lambda: FakeCredential())
        monkeypatch.setattr(generate_gallery, "FoundryService", lambda credential: first_service)

        first_exit = asyncio.run(generate_gallery.generate_gallery(concurrency=1, force=False))
        assert first_exit == 1

        manifest = generate_gallery.MANIFEST_PATH.read_text(encoding="utf-8")
        assert "p1" in manifest
        assert '"status": "failed"' in manifest or '"status": "partial"' in manifest

        class StableService(FakeService):
            async def generate_image(self, *, model: str, prompt: str, image=None, image_filename=None, image_content_type=None):
                self.calls += 1
                return type(
                    "Result",
                    (),
                    {
                        "data_url": "data:image/png;base64,cG5n",
                        "metadata": {"size": "1x1"},
                    },
                )()

        second_service = StableService()
        monkeypatch.setattr(generate_gallery, "FoundryService", lambda credential: second_service)
        second_exit = asyncio.run(generate_gallery.generate_gallery(concurrency=1, force=False))

        assert second_exit == 0
        assert second_service.calls == 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
