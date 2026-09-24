from __future__ import annotations

import argparse
import threading
import time
import wave
from pathlib import Path

from app.speech import (
    ConfigurationError,
    create_translation_config,
    format_cancellation,
    load_speech_sdk,
    pcm_to_wav,
    settings_from_values,
    translations,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate microphone or WAV speech with Azure Speech Live Interpreter.")
    parser.add_argument("--target-language", default="fr")
    parser.add_argument("--voice")
    parser.add_argument("--wav", type=Path)
    parser.add_argument("--output-wav", type=Path, default=Path("translated.wav"))
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    try:
        settings = settings_from_values(args.target_language, args.voice)
        speechsdk = load_speech_sdk()
        translation_config, auto_detect = create_translation_config(settings, speechsdk)
        audio_config = (
            speechsdk.audio.AudioConfig(filename=str(args.wav))
            if args.wav
            else speechsdk.audio.AudioConfig(use_default_microphone=True)
        )
        recognizer = speechsdk.translation.TranslationRecognizer(
            translation_config=translation_config,
            auto_detect_source_language_config=auto_detect,
            audio_config=audio_config,
        )
    except (ConfigurationError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2

    done = threading.Event()
    canceled: list[str] = []
    audio: list[bytes] = []
    recognizer.recognizing.connect(
        lambda event: print(f"… {getattr(event.result, 'text', '')} -> {translations(event.result)}")
    )
    recognizer.recognized.connect(
        lambda event: print(f"✓ {getattr(event.result, 'text', '')} -> {translations(event.result)}")
    )
    recognizer.synthesizing.connect(
        lambda event: audio.append(bytes(getattr(event.result, "audio", b"") or b""))
    )
    recognizer.canceled.connect(
        lambda event: (canceled.append(format_cancellation(event, settings.voice_name)), done.set())
    )
    recognizer.session_stopped.connect(lambda _: done.set())
    recognizer.start_continuous_recognition()
    deadline = time.monotonic() + args.timeout
    try:
        while not done.wait(0.1) and time.monotonic() < deadline:
            pass
    except KeyboardInterrupt:
        pass
    finally:
        recognizer.stop_continuous_recognition()
    if audio:
        args.output_wav.write_bytes(pcm_to_wav(audio))
        print(f"Audio written to {args.output_wav}")
    if canceled:
        print(f"ERROR: {canceled[0]}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
