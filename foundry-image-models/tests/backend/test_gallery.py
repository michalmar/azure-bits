from __future__ import annotations

import asyncio
import json
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


def test_shipped_gallery_contains_twelve_images_for_four_models():
    service = FoundryService(credential=object())
    with make_client(service) as client:
        response = client.get("/api/gallery")

    assert response.status_code == 200
    manifest = response.json()
    models = {
        "gpt-image-2.5-sunburst",
        "MAI-Image-2.6-Flash",
        "MAI-Image-2.6",
        "gpt-image-2",
    }
    prompts = {prompt["id"]: prompt for prompt in manifest["prompts"]}
    assert len(prompts) == 3
    assert len(manifest["results"]) == 12
    assert {(item["promptId"], item["model"]) for item in manifest["results"]} == {
        (prompt_id, model) for prompt_id in prompts for model in models
    }
    files = set()
    for item in manifest["results"]:
        assert item["status"] == "generated"
        assert item["prompt"] == prompts[item["promptId"]]["prompt"]
        path = Path("static/gallery") / item["file"]
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        files.add(path)
    assert files == set(Path("static/gallery").glob("*/*.png"))


def test_gallery_generator_drops_retired_results_without_regenerating_existing_images(monkeypatch, tmp_path):
    from scripts import generate_gallery

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(generate_gallery, "AzureCliCredential", lambda: object())
    models = (
        "gpt-image-2.5-sunburst",
        "MAI-Image-2.6-Flash",
        "MAI-Image-2.6",
        "gpt-image-2",
    )
    results = []
    for prompt in GALLERY_PROMPTS:
        for model in (*models, "MAI-Image-2.5"):
            target = Path("static/gallery") / prompt["id"] / (model.lower().replace(".", "-") + ".png")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"existing image")
            results.append({
                "promptId": prompt["id"],
                "model": model,
                "file": str(target.relative_to("static/gallery")),
                "status": "generated",
            })

    manifest_path = Path("static/gallery/manifest.json")
    manifest_path.write_text(json.dumps({"prompts": list(GALLERY_PROMPTS), "results": results}))

    assert asyncio.run(generate_gallery.generate_gallery(concurrency=2, force=False)) == 0

    manifest = json.loads(manifest_path.read_text())
    assert len(manifest["results"]) == 12
    assert {item["model"] for item in manifest["results"]} == set(models)
    assert manifest["status"] == "complete"
    assert manifest["failedCount"] == 0
    for item in manifest["results"]:
        assert (manifest_path.parent / item["file"]).read_bytes() == b"existing image"


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
