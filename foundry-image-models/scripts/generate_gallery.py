from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from azure.identity import AzureCliCredential

from app.config import ALLOWED_MODELS
from app.prompts import GALLERY_PROMPTS
from app.service import FoundryService


LOG = logging.getLogger("foundry-image-models.generate_gallery")
OUTPUT_DIR = Path("static/gallery")
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
MAX_CONCURRENCY = 2


def _slugify(value: str) -> str:
    slug = []
    for char in value.lower():
        if char.isalnum():
            slug.append(char)
        elif slug and slug[-1] != "-":
            slug.append("-")
    return "".join(slug).strip("-") or "item"


def _model_file(prompt_id: str, model: str) -> Path:
    prompt_dir = OUTPUT_DIR / _slugify(prompt_id)
    return prompt_dir / f"{_slugify(model)}.png"


def _load_manifest() -> dict[str, Any]:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        "prompts": list(GALLERY_PROMPTS),
        "results": [],
    }


def _save_manifest(manifest: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = MANIFEST_PATH.with_name(f"{MANIFEST_PATH.name}.tmp")
    temp_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp_path.replace(MANIFEST_PATH)


def _result_key(result: dict[str, Any]) -> tuple[str, str]:
    return result["promptId"], result["model"]


def _result_from_file(prompt: dict[str, str], model: str) -> dict[str, Any]:
    target = _model_file(prompt["id"], model)
    return {
        "promptId": prompt["id"],
        "prompt": prompt["prompt"],
        "label": prompt["label"],
        "model": model,
        "file": str(target.relative_to(OUTPUT_DIR)),
        "status": "generated",
    }


def _failure_result(prompt: dict[str, str], model: str, error: str) -> dict[str, Any]:
    return {
        "promptId": prompt["id"],
        "prompt": prompt["prompt"],
        "label": prompt["label"],
        "model": model,
        "status": "failed",
        "error": error,
    }


def _sync_existing_results(manifest: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    results: dict[tuple[str, str], dict[str, Any]] = {}
    for item in manifest.get("results", []):
        if isinstance(item, dict) and item.get("status") == "generated":
            results[_result_key(item)] = item
    for prompt in GALLERY_PROMPTS:
        for model in ALLOWED_MODELS:
            target = _model_file(prompt["id"], model)
            if target.exists():
                results.setdefault((prompt["id"], model), _result_from_file(prompt, model))
    return results


async def _generate_one(service: FoundryService, prompt: dict[str, str], model: str, force: bool) -> dict[str, Any] | None:
    target = _model_file(prompt["id"], model)
    if not force and target.exists():
        LOG.info("skip existing image prompt=%s model=%s file=%s", prompt["id"], model, target)
        return _result_from_file(prompt, model)

    LOG.info("generate prompt=%s model=%s", prompt["id"], model)
    result = await service.generate_image(model=model, prompt=prompt["prompt"])
    target.parent.mkdir(parents=True, exist_ok=True)
    image_bytes = base64.b64decode(result.data_url.split(",", 1)[1])
    target.write_bytes(image_bytes)
    payload = _result_from_file(prompt, model)
    payload["metadata"] = result.metadata
    return payload


async def generate_gallery(concurrency: int, force: bool) -> int:
    credential = AzureCliCredential()
    service = FoundryService(credential=credential)
    try:
        manifest = _load_manifest()
        manifest["prompts"] = list(GALLERY_PROMPTS)
        existing = _sync_existing_results(manifest)

        effective_concurrency = max(1, min(concurrency, MAX_CONCURRENCY))
        if effective_concurrency != concurrency:
            LOG.info("capped concurrency from %s to %s", concurrency, effective_concurrency)

        semaphore = asyncio.Semaphore(effective_concurrency)
        manifest_lock = asyncio.Lock()
        jobs: list[asyncio.Task[dict[str, Any] | None]] = []

        async def run_job(prompt: dict[str, str], model: str) -> dict[str, Any] | None:
            async with semaphore:
                try:
                    item = await _generate_one(service, prompt, model, force)
                except Exception as exc:
                    LOG.exception("gallery generation failed prompt=%s model=%s", prompt["id"], model)
                    item = _failure_result(prompt, model, str(exc))
            if item is None:
                return None
            async with manifest_lock:
                existing[(item["promptId"], item["model"])] = item
                manifest["results"] = [existing[key] for key in sorted(existing)]
                _save_manifest(manifest)
            return item

        for prompt in GALLERY_PROMPTS:
            for model in ALLOWED_MODELS:
                key = (prompt["id"], model)
                if not force and key in existing and _model_file(prompt["id"], model).exists():
                    LOG.info("keep existing success prompt=%s model=%s", prompt["id"], model)
                    continue
                jobs.append(asyncio.create_task(run_job(prompt, model)))

        failures = 0
        if jobs:
            for job in asyncio.as_completed(jobs):
                try:
                    item = await job
                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    LOG.exception("gallery generation orchestration failed: %s", exc)
                    failures += 1
                    continue
                if item and item.get("status") == "failed":
                    failures += 1

        manifest["results"] = [existing[key] for key in sorted(existing)]
        manifest["status"] = "partial" if failures else "complete"
        manifest["failedCount"] = failures
        _save_manifest(manifest)
        LOG.info("wrote manifest with %s results", len(manifest["results"]))
        return 1 if failures else 0
    finally:
        await service.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the Foundry comparison gallery.")
    parser.add_argument("--concurrency", type=int, default=2, help="Concurrent model generations, capped at 2.")
    parser.add_argument("--force", action="store_true", help="Regenerate all gallery images even if files exist.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    return asyncio.run(generate_gallery(concurrency=args.concurrency, force=args.force))


if __name__ == "__main__":
    raise SystemExit(main())
