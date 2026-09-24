from __future__ import annotations

import io
import wave

import pytest

from app import speech


def test_build_endpoint_normalizes_resource_and_url():
    assert speech.build_endpoint("demo-speech") == (
        "wss://demo-speech.cognitiveservices.azure.com/stt/speech/universal/v2"
    )
    assert speech.build_endpoint(None, "https://demo.example.com") == (
        "wss://demo.example.com/stt/speech/universal/v2"
    )


@pytest.mark.parametrize(
    "endpoint",
    ["http://demo.example.com", "https://demo.example.com/wrong", "https://user@example.com"],
)
def test_build_endpoint_rejects_unsafe_values(endpoint):
    with pytest.raises(speech.ConfigurationError):
        speech.build_endpoint(None, endpoint)


def test_voice_defaults_and_aliases():
    assert speech.normalize_language("cz") == "cs"
    assert speech.resolve_voice("fr", None) == "fr-FR-DeniseNeural"
    assert speech.resolve_voice("fr", "personal-voice") == "personal-voice"
    with pytest.raises(speech.ConfigurationError):
        speech.resolve_voice("ja", None)


def test_pcm_to_wav_wraps_raw_audio():
    payload = speech.pcm_to_wav([b"\x00\x00" * 32])
    with wave.open(io.BytesIO(payload), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16000
        assert wav_file.getnframes() == 32


def test_pcm_to_wav_merges_wav_chunks_without_nested_headers():
    first = speech.pcm_to_wav([b"\x01\x00" * 8])
    second = speech.pcm_to_wav([b"\x02\x00" * 12])
    merged = speech.pcm_to_wav([first, second])
    with wave.open(io.BytesIO(merged), "rb") as wav_file:
        assert wav_file.getnframes() == 20
        frames = wav_file.readframes(20)
    assert frames == (b"\x01\x00" * 8) + (b"\x02\x00" * 12)


def test_synthesis_chunk_format_detects_wav_and_pcm():
    wav_chunk = speech.pcm_to_wav([b"\x00\x00" * 4])
    assert speech.synthesis_chunk_format(wav_chunk) == "wav"
    assert speech.synthesis_chunk_format(b"\x00\x00" * 4) == "pcm16"
