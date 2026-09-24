from __future__ import annotations

import io
import os
import wave
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from azure.identity import AzureCliCredential, ManagedIdentityCredential


PERSONAL_VOICE = "personal-voice"
UNIVERSAL_V2_PATH = "/stt/speech/universal/v2"
OUTPUT_SAMPLE_RATE = 16000
OUTPUT_CHANNELS = 1
OUTPUT_SAMPLE_WIDTH = 2
DEFAULT_VOICES = {
    "fr": "fr-FR-DeniseNeural",
    "en": "en-US-JennyNeural",
    "cs": "en-US-Ava:DragonHDLatestNeural",
    "de": "de-DE-KatjaNeural",
    "es": "es-ES-ElviraNeural",
    "it": "it-IT-ElsaNeural",
}
SYNTHESIS_LOCALES = {
    "fr": "fr-FR",
    "en": "en-US",
    "cs": "cs-CZ",
    "de": "de-DE",
    "es": "es-ES",
    "it": "it-IT",
}


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SpeechSettings:
    endpoint: str
    target_language: str
    voice_name: str


def build_endpoint(resource_name: str | None, endpoint: str | None = None) -> str:
    if endpoint:
        parsed = urlsplit(endpoint.strip())
        if parsed.scheme not in {"https", "wss"} or not parsed.hostname:
            raise ConfigurationError("AZURE_SPEECH_ENDPOINT must be an https:// or wss:// endpoint.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfigurationError("AZURE_SPEECH_ENDPOINT cannot contain credentials or query data.")
        path = parsed.path.rstrip("/")
        if path and path != UNIVERSAL_V2_PATH:
            raise ConfigurationError(f"AZURE_SPEECH_ENDPOINT must use {UNIVERSAL_V2_PATH}.")
        return urlunsplit(("wss", parsed.netloc, UNIVERSAL_V2_PATH, "", ""))

    name = (resource_name or "").strip()
    if not name or not all(character.isalnum() or character == "-" for character in name):
        raise ConfigurationError("Set a valid AZURE_SPEECH_RESOURCE_NAME.")
    return f"wss://{name}.cognitiveservices.azure.com{UNIVERSAL_V2_PATH}"


def normalize_language(value: str) -> str:
    language = value.strip().lower()
    return "cs" if language == "cz" else language


def resolve_voice(target_language: str, requested_voice: str | None) -> str:
    if requested_voice and requested_voice.strip():
        return requested_voice.strip()
    language = normalize_language(target_language).split("-", 1)[0]
    if language not in DEFAULT_VOICES:
        raise ConfigurationError(f"Choose an explicit voice for target language {target_language!r}.")
    return DEFAULT_VOICES[language]


def settings_from_values(target_language: str, voice_name: str | None = None) -> SpeechSettings:
    language = normalize_language(target_language)
    if not language:
        raise ConfigurationError("A target language is required.")
    return SpeechSettings(
        endpoint=build_endpoint(
            os.getenv("AZURE_SPEECH_RESOURCE_NAME"),
            os.getenv("AZURE_SPEECH_ENDPOINT"),
        ),
        target_language=language,
        voice_name=resolve_voice(language, voice_name),
    )


def credential() -> Any:
    client_id = os.getenv("AZURE_CLIENT_ID", "").strip()
    if client_id:
        return ManagedIdentityCredential(client_id=client_id)
    return AzureCliCredential(
        tenant_id=os.getenv("AZURE_TENANT_ID") or None,
        subscription=os.getenv("AZURE_SUBSCRIPTION_ID") or None,
    )


def load_speech_sdk() -> Any:
    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError as exc:
        raise ConfigurationError("Install azure-cognitiveservices-speech.") from exc
    return speechsdk


def create_translation_config(settings: SpeechSettings, speechsdk: Any) -> tuple[Any, Any]:
    config = speechsdk.translation.SpeechTranslationConfig(
        token_credential=credential(),
        endpoint=settings.endpoint,
    )
    config.add_target_language(settings.target_language)
    config.voice_name = settings.voice_name
    locale = SYNTHESIS_LOCALES.get(settings.target_language.split("-", 1)[0])
    if locale:
        config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_SynthLanguage,
            locale,
        )
    config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Raw16Khz16BitMonoPcm
    )
    return config, speechsdk.languageconfig.AutoDetectSourceLanguageConfig()


def format_cancellation(event: Any, voice_name: str) -> str:
    details = getattr(event, "cancellation_details", None)
    reason = getattr(details, "reason", "unknown")
    error = getattr(details, "error_details", "")
    message = f"Speech session canceled: {reason}"
    if error:
        message += f"; {error}"
    lowered = f"{reason} {error}".lower()
    if voice_name == PERSONAL_VOICE and ("live interpreter" in lowered or "personal voice" in lowered):
        message += " Verify Personal Voice approval on this exact Speech resource."
    elif "live interpreter" in lowered:
        message += " Verify Live Interpreter approval on this exact Speech resource."
    return message


def translations(result: Any) -> dict[str, str]:
    values = getattr(result, "translations", {}) or {}
    return {str(language): str(text) for language, text in values.items() if text}


def pcm_to_wav(chunks: list[bytes]) -> bytes:
    if chunks and all(chunk.startswith(b"RIFF") and b"WAVE" in chunk[:16] for chunk in chunks):
        first_params: tuple[int, int, int] | None = None
        frames = bytearray()
        for chunk in chunks:
            with wave.open(io.BytesIO(chunk), "rb") as source:
                params = (
                    source.getnchannels(),
                    source.getsampwidth(),
                    source.getframerate(),
                )
                if first_params is None:
                    first_params = params
                elif params != first_params:
                    raise ValueError("Synthesized WAV chunks use different audio formats.")
                frames.extend(source.readframes(source.getnframes()))
        if first_params is not None:
            return _wav_bytes(bytes(frames), *first_params)
    return _wav_bytes(
        b"".join(chunks),
        OUTPUT_CHANNELS,
        OUTPUT_SAMPLE_WIDTH,
        OUTPUT_SAMPLE_RATE,
    )


def synthesis_chunk_format(audio: bytes) -> str:
    return "wav" if audio.startswith(b"RIFF") and b"WAVE" in audio[:16] else "pcm16"


def _wav_bytes(audio: bytes, channels: int, sample_width: int, sample_rate: int) -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(sample_width)
        output.setframerate(sample_rate)
        output.writeframes(audio)
    return stream.getvalue()
