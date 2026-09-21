from __future__ import annotations

from dataclasses import dataclass, field
import base64
import json
import time
from pathlib import Path
from typing import Any

import anyio
import httpx
from azure.identity import AzureCliCredential, ManagedIdentityCredential

from .config import (
    ALLOWED_MODELS,
    CAPABILITY_CACHE_SECONDS,
    DATA_SCOPE,
    MAX_PROMPT_LENGTH,
    MGMT_API_VERSION,
    MANAGEMENT_SCOPE,
    MODEL_DEPLOYMENT,
    MODEL_PROVIDER,
    OPENAI_API_VERSION,
    UPSTREAM_TIMEOUT_SECONDS,
    get_defaults,
)
from .prompts import GALLERY_PROMPTS


@dataclass(slots=True)
class CapabilityState:
    status: str
    image_edits: bool | None = None
    error: str | None = None
    source: str | None = None
    stale: bool = False
    last_known: dict[str, Any] | None = None


@dataclass(slots=True)
class ImageResult:
    data_url: str
    mime_type: str
    filename: str
    model: str
    prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "dataUrl": self.data_url,
            "mimeType": self.mime_type,
            "filename": self.filename,
            "model": self.model,
            "prompt": self.prompt,
        }
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


class CapabilityLookupError(RuntimeError):
    pass


class UnsupportedImageInputError(RuntimeError):
    pass


class FoundryService:
    def __init__(
        self,
        credential: object | None = None,
        http_client: httpx.AsyncClient | None = None,
        defaults: object | None = None,
        capability_cache_seconds: int = CAPABILITY_CACHE_SECONDS,
    ) -> None:
        self.defaults = defaults or get_defaults()
        self.credential = credential or self._build_default_credential()
        self.http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(UPSTREAM_TIMEOUT_SECONDS))
        self.capability_cache_seconds = capability_cache_seconds
        self._capability_cache_at = 0.0
        self._capability_cache: dict[str, CapabilityState] = {}
        self._capability_cache_error: str | None = None

    def _build_default_credential(self) -> object:
        if self._app_env() == "production":
            client_id = self._azure_client_id()
            return ManagedIdentityCredential(client_id=client_id)
        return AzureCliCredential()

    def _app_env(self) -> str:
        import os

        return os.getenv("APP_ENV", "development").lower()

    def _azure_client_id(self) -> str | None:
        import os

        value = os.getenv("AZURE_CLIENT_ID")
        return value or None

    async def close(self) -> None:
        await self.http.aclose()

    async def _token_headers(self, scope: str) -> dict[str, str]:
        token = await anyio.to_thread.run_sync(self.credential.get_token, scope)
        return {"Authorization": "Bearer " + token.token}

    async def _request(self, method: str, url: str, scope: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.update(await self._token_headers(scope))
        response = await self.http.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        return response

    def management_models_url(self) -> str:
        return (
            "https://management.azure.com/subscriptions/"
            f"{self.defaults.subscription_id}/resourceGroups/{self.defaults.resource_group}"
            f"/providers/Microsoft.CognitiveServices/accounts/{self.defaults.account_name}/models"
            f"?api-version={MGMT_API_VERSION}"
        )

    def openai_generation_url(self, model: str, edits: bool = False) -> str:
        deployment = MODEL_DEPLOYMENT.get(model, model)
        suffix = "edits" if edits else "generations"
        return (
            f"{self.defaults.base_url}/openai/deployments/{deployment}/images/{suffix}"
            f"?api-version={OPENAI_API_VERSION}"
        )

    def mai_generation_url(self, edits: bool = False) -> str:
        suffix = "edits" if edits else "generations"
        return f"{self.defaults.base_url}/mai/v1/images/{suffix}"

    def _cache_is_fresh(self) -> bool:
        return (time.time() - self._capability_cache_at) < self.capability_cache_seconds

    def _model_entry(self, model: str, capability: CapabilityState | None) -> dict[str, Any]:
        provider = MODEL_PROVIDER[model]
        entry = {
            "name": model,
            "provider": provider,
        }
        if provider == "openai":
            entry["deployment"] = MODEL_DEPLOYMENT[model]
        entry["capabilities"] = {
            "imageEdits": self._capability_payload(capability, model),
        }
        return entry

    def _capability_payload(self, capability: CapabilityState | None, model: str) -> dict[str, Any]:
        if capability is None:
            return {"status": "error", "error": f"{model}: capability unavailable"}
        payload: dict[str, Any] = {"status": capability.status}
        if capability.image_edits is not None:
            payload["value"] = capability.image_edits
        if capability.error:
            payload["error"] = capability.error
        if capability.source:
            payload["source"] = capability.source
        if capability.stale:
            payload["stale"] = True
        if capability.last_known is not None:
            payload["lastKnown"] = capability.last_known
        return payload

    def _normalize_bool(self, value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "enabled", "supported"}:
                return True
            if normalized in {"false", "0", "no", "disabled", "unsupported"}:
                return False
        if isinstance(value, dict):
            for key in ("supported", "enabled", "value", "isEnabled", "isSupported"):
                candidate = self._normalize_bool(value.get(key))
                if candidate is not None:
                    return candidate
            return None
        return None

    def _parse_management_payload(self, payload: Any) -> dict[str, CapabilityState]:
        if isinstance(payload, dict):
            candidates = payload.get("value")
            if not isinstance(candidates, list):
                candidates = payload.get("models")
            if not isinstance(candidates, list):
                candidates = payload.get("data")
            if not isinstance(candidates, list):
                candidates = []
        elif isinstance(payload, list):
            candidates = payload
        else:
            candidates = []

        found: dict[str, CapabilityState] = {}
        for item in candidates:
            if not isinstance(item, dict):
                continue
            name = (
                item.get("name")
                or item.get("modelName")
                or item.get("model")
                or item.get("deploymentName")
                or item.get("id")
            )
            if not isinstance(name, str) or not name:
                continue
            capabilities = item.get("capabilities")
            if not isinstance(capabilities, dict):
                properties = item.get("properties")
                if isinstance(properties, dict):
                    capabilities = properties.get("capabilities") if isinstance(properties.get("capabilities"), dict) else properties
                else:
                    capabilities = {}
            image_edits = None
            if isinstance(capabilities, dict):
                if "imageEdits" in capabilities:
                    image_edits = self._normalize_bool(capabilities.get("imageEdits"))
                else:
                    inner = capabilities.get("imageEditsCapability")
                    if inner is not None:
                        image_edits = self._normalize_bool(inner)
            if image_edits is None:
                found[name] = CapabilityState(
                    status="error",
                    error="imageEdits capability missing from management response",
                    source="management",
                )
            else:
                found[name] = CapabilityState(
                    status="ready" if image_edits else "unsupported",
                    image_edits=image_edits,
                    source="management",
                )
        return found

    async def model_capabilities(self, refresh: bool = False) -> dict[str, CapabilityState]:
        if not refresh and self._capability_cache and self._cache_is_fresh():
            return dict(self._capability_cache)

        try:
            response = await self._request("GET", self.management_models_url(), MANAGEMENT_SCOPE)
            parsed = self._parse_management_payload(response.json())
            capabilities = {
                model: parsed.get(model)
                if parsed.get(model) is not None
                else CapabilityState(
                    status="error",
                    error="model not present in management response",
                    source="management",
                )
                for model in ALLOWED_MODELS
            }
            self._capability_cache = capabilities
            self._capability_cache_at = time.time()
            self._capability_cache_error = None
            return dict(capabilities)
        except Exception as exc:
            error = f"management capability lookup failed: {exc}"
            if self._capability_cache:
                stale = {
                    model: CapabilityState(
                        status="error",
                        error=error,
                        source="management",
                        stale=True,
                        last_known={
                            "status": cached.status,
                            "value": cached.image_edits,
                            "source": cached.source,
                        },
                    )
                    for model, cached in self._capability_cache.items()
                }
                self._capability_cache_error = error
                return stale
            return {
                model: CapabilityState(status="error", error=error, source="management")
                for model in ALLOWED_MODELS
            }

    async def capability_for_model(self, model: str, refresh: bool = False) -> CapabilityState:
        capabilities = await self.model_capabilities(refresh=refresh)
        capability = capabilities[model]
        if capability.status != "ready" or capability.image_edits is not True:
            detail = capability.error or f"{model} image input is not available"
            raise CapabilityLookupError(detail)
        return capability

    def list_models_payload(self, capabilities: dict[str, CapabilityState]) -> dict[str, Any]:
        return {"models": [self._model_entry(model, capabilities.get(model)) for model in ALLOWED_MODELS]}

    def _safe_metadata(self, response_json: dict[str, Any]) -> dict[str, Any]:
        safe_keys = {"size", "quality", "background", "style", "seed", "format"}
        metadata: dict[str, Any] = {}
        for key in safe_keys:
            value = response_json.get(key)
            if value is not None:
                metadata[key] = value
        data = response_json.get("data")
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                for key in safe_keys:
                    value = first.get(key)
                    if value is not None and key not in metadata:
                        metadata[key] = value
        return metadata

    def _extract_b64(self, response_json: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        data = response_json.get("data")
        if not isinstance(data, list) or not data:
            raise ValueError("response did not include data[0]")
        first = data[0]
        if not isinstance(first, dict):
            raise ValueError("response data[0] was not an object")
        b64 = first.get("b64_json")
        if not isinstance(b64, str) or not b64:
            raise ValueError("response data[0].b64_json missing")
        return b64, self._safe_metadata(response_json)

    async def generate_image(
        self,
        *,
        model: str,
        prompt: str,
        image: bytes | None = None,
        image_filename: str | None = None,
        image_content_type: str | None = None,
    ) -> ImageResult:
        if model not in ALLOWED_MODELS:
            raise ValueError(f"unsupported model: {model}")
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt must not be empty")
        if len(prompt) > MAX_PROMPT_LENGTH:
            raise ValueError(f"prompt must be {MAX_PROMPT_LENGTH} characters or fewer")

        provider = MODEL_PROVIDER[model]
        if image is None:
            if provider == "mai":
                payload = {"model": model, "prompt": prompt}
                response = await self._request("POST", self.mai_generation_url(edits=False), DATA_SCOPE, json=payload)
            else:
                payload = {"prompt": prompt}
                response = await self._request(
                    "POST",
                    self.openai_generation_url(model, edits=False),
                    DATA_SCOPE,
                    json=payload,
                )
        else:
            capability = await self.capability_for_model(model, refresh=True)

            files = {
                "image": (
                    image_filename or "upload.png",
                    image,
                    image_content_type or "application/octet-stream",
                )
            }
            if provider == "mai":
                data = {"model": model, "prompt": prompt}
                response = await self._request(
                    "POST",
                    self.mai_generation_url(edits=True),
                    DATA_SCOPE,
                    data=data,
                    files=files,
                )
            else:
                data = {"prompt": prompt}
                response = await self._request(
                    "POST",
                    self.openai_generation_url(model, edits=True),
                    DATA_SCOPE,
                    data=data,
                    files=files,
                )

        response_json = response.json()
        b64, metadata = self._extract_b64(response_json)
        data_url = f"data:image/png;base64,{b64}"
        return ImageResult(
            data_url=data_url,
            mime_type="image/png",
            filename="generated.png",
            model=model,
            prompt=prompt,
            metadata=metadata,
        )

    def gallery_manifest_path(self) -> Path:
        return Path("static/gallery/manifest.json")

    def gallery_root(self) -> Path:
        return self.gallery_manifest_path().parent

    def default_gallery_manifest(self) -> dict[str, Any]:
        return {
            "prompts": list(GALLERY_PROMPTS),
            "results": [],
            "generationGuidance": "Run scripts/generate_gallery.py to create the 15-image comparison gallery.",
        }

    def read_gallery_manifest(self) -> dict[str, Any]:
        path = self.gallery_manifest_path()
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return self.default_gallery_manifest()

    @staticmethod
    def decode_b64_png(data_url_or_b64: str) -> bytes:
        if data_url_or_b64.startswith("data:"):
            _, _, payload = data_url_or_b64.partition(",")
        else:
            payload = data_url_or_b64
        return base64.b64decode(payload)
