from __future__ import annotations

from dataclasses import dataclass, field
import os


DATA_SCOPE = "https://cognitiveservices.azure.com/.default"
MAX_INPUT_CHARS = 60_000
MAX_BURST_REQUESTS = 20


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD per one million tokens."""

    input: float
    cached_input: float
    output: float


@dataclass(frozen=True, slots=True)
class Profile:
    """A model tier ("large" or "small") and the prompt contract it is called with."""

    tier: str
    model_id: str
    max_output_tokens: int
    price: ModelPrice
    temperature: float | None = None
    reasoning_effort: str | None = None


@dataclass(frozen=True, slots=True)
class Settings:
    foundry_endpoint: str
    direct_large_deployment: str
    gateway_endpoint: str
    gateway_primary_model: str
    gateway_fallback_model: str
    gateway_app_key: str = field(repr=False)
    gateway_burst_key: str = field(repr=False)
    gateway_app_key_name: str
    gateway_burst_key_name: str
    burst_model: str
    fallback_on: frozenset[str]
    large: Profile
    small: Profile
    request_timeout_seconds: float
    audit_log_path: str

    @property
    def gateway_configured(self) -> bool:
        return bool(self.gateway_endpoint and self.gateway_app_key)

    @property
    def burst_key_configured(self) -> bool:
        return bool(self.gateway_endpoint and self.gateway_burst_key)

    @classmethod
    def from_env(cls) -> "Settings":
        foundry = _https("FOUNDRY_OPENAI_ENDPOINT", "https://aif-mma-eus.openai.azure.com")
        gateway = os.getenv("GATEWAY_ENDPOINT", "").strip().rstrip("/")
        if gateway and not gateway.startswith("https://"):
            raise ValueError("GATEWAY_ENDPOINT must be an HTTPS URL.")
        temperature = _opt_float("TEMPERATURE", 0.2)
        primary = _text("GATEWAY_PRIMARY_MODEL", "summarizer-large")
        fallback_on = frozenset(
            v.strip()
            for v in os.getenv("FALLBACK_ON", "token_limit_exceeded,cost_limit_exceeded").split(",")
            if v.strip()
        )
        large = Profile(
            tier="large",
            model_id=_text("LARGE_MODEL_ID", "gpt-4.1"),
            max_output_tokens=_int("LARGE_MAX_OUTPUT_TOKENS", 1000, 16, 4096),
            price=ModelPrice(
                input=_float("LARGE_PRICE_INPUT_PER_1M", 2.00),
                cached_input=_float("LARGE_PRICE_CACHED_INPUT_PER_1M", 0.50),
                output=_float("LARGE_PRICE_OUTPUT_PER_1M", 8.00),
            ),
            temperature=_opt_float("LARGE_TEMPERATURE", temperature),
            reasoning_effort=os.getenv("LARGE_REASONING_EFFORT", "").strip() or None,
        )
        small = Profile(
            tier="small",
            model_id=_text("SMALL_MODEL_ID", "gpt-4.1-nano"),
            max_output_tokens=_int("SMALL_MAX_OUTPUT_TOKENS", 350, 16, 4096),
            price=ModelPrice(
                input=_float("SMALL_PRICE_INPUT_PER_1M", 0.10),
                cached_input=_float("SMALL_PRICE_CACHED_INPUT_PER_1M", 0.025),
                output=_float("SMALL_PRICE_OUTPUT_PER_1M", 0.40),
            ),
            temperature=_opt_float("SMALL_TEMPERATURE", temperature),
            reasoning_effort=os.getenv("SMALL_REASONING_EFFORT", "").strip() or None,
        )
        return cls(
            foundry_endpoint=foundry,
            direct_large_deployment=_text("DIRECT_LARGE_DEPLOYMENT", "gpt-4.1"),
            gateway_endpoint=gateway,
            gateway_primary_model=primary,
            gateway_fallback_model=_text("GATEWAY_FALLBACK_MODEL", "summarizer-small"),
            gateway_app_key=os.getenv("GATEWAY_APP_KEY", "").strip(),
            gateway_burst_key=os.getenv("GATEWAY_BURST_KEY", "").strip(),
            gateway_app_key_name=_text("GATEWAY_APP_KEY_NAME", "summarizer-app"),
            gateway_burst_key_name=_text("GATEWAY_BURST_KEY_NAME", "burst-client"),
            burst_model=os.getenv("GATEWAY_BURST_MODEL", "").strip() or primary,
            fallback_on=fallback_on,
            large=large,
            small=small,
            request_timeout_seconds=_float("REQUEST_TIMEOUT_SECONDS", 120.0),
            audit_log_path=os.getenv("AUDIT_LOG_PATH", "logs/audit.jsonl"),
        )


def _https(name: str, default: str) -> str:
    value = os.getenv(name, default).strip().rstrip("/")
    if not value.startswith("https://"):
        raise ValueError(f"{name} must be an HTTPS URL.")
    return value


def _text(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    if not value:
        raise ValueError(f"{name} must not be empty.")
    return value


def _int(name: str, default: int, low: int, high: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}.")
    return value


def _float(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value < 0:
        raise ValueError(f"{name} must not be negative.")
    return value


def _opt_float(name: str, default: float | None) -> float | None:
    """An empty value omits the parameter, for models that accept only their default."""
    raw = os.getenv(name)
    if raw is None:
        return default
    if not raw.strip():
        return None
    return _float(name, default or 0)
