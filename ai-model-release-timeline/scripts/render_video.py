"""Render the model release timeline animation to an MP4 video.

The animation is drawn by ``static/timeline.js``. This script serves the
``static`` folder locally, steps the deterministic renderer frame by frame in
headless Chromium, and pipes the frames to ffmpeg.
"""

from __future__ import annotations

import argparse
import base64
import functools
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

DEMO_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = DEMO_DIR / "static"
DEFAULT_OUTPUT = DEMO_DIR / "media" / "model-release-timeline.mp4"
DEFAULT_POSTER = DEMO_DIR / "media" / "poster.png"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


def serve_static() -> ThreadingHTTPServer:
    handler = functools.partial(QuietHandler, directory=str(STATIC_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def decode(data_url: str) -> bytes:
    return base64.b64decode(data_url.split(",", 1)[1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--poster", type=Path, default=DEFAULT_POSTER)
    parser.add_argument("--poster-time", type=float, default=40.0)
    parser.add_argument(
        "--stills",
        type=float,
        nargs="*",
        help="Only write PNG stills at these times (seconds) next to --output.",
    )
    args = parser.parse_args()

    if args.fps <= 0:
        parser.error("--fps must be greater than zero")
    if args.poster_time < 0:
        parser.error("--poster-time cannot be negative")

    server = serve_static()
    url = f"http://127.0.0.1:{server.server_address[1]}/render.html"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.poster.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1920, "height": 1080})
                page.goto(url, wait_until="networkidle")
                page.wait_for_function("window.timelineReady === true")
                duration = float(page.evaluate("window.timelineDuration"))

                if args.stills is not None:
                    for t in args.stills:
                        if not 0 <= t <= duration:
                            parser.error(f"still time {t} is outside the 0–{duration:.1f}s timeline")
                        still = args.output.with_name(f"still-{t:05.1f}.png")
                        still.write_bytes(decode(page.evaluate("t => window.renderFrame(t)", t)))
                        print(f"Wrote {still}")
                    return

                poster_time = min(args.poster_time, duration)
                args.poster.write_bytes(
                    decode(page.evaluate("t => window.renderFrame(t)", poster_time))
                )
                print(f"Wrote {args.poster}")

                frames = int(round(duration * args.fps))
                ffmpeg = subprocess.Popen(
                    [
                        imageio_ffmpeg.get_ffmpeg_exe(),
                        "-y",
                        "-loglevel", "error",
                        "-f", "image2pipe",
                        "-framerate", str(args.fps),
                        "-c:v", "png",
                        "-i", "-",
                        "-c:v", "libx264",
                        "-preset", "slow",
                        "-crf", "20",
                        "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart",
                        str(args.output),
                    ],
                    stdin=subprocess.PIPE,
                )
                assert ffmpeg.stdin is not None
                try:
                    for i in range(frames + 1):
                        frame = page.evaluate("t => window.renderFrame(t)", i / args.fps)
                        ffmpeg.stdin.write(decode(frame))
                        if i % (args.fps * 5) == 0:
                            print(f"Frame {i}/{frames}")
                finally:
                    ffmpeg.stdin.close()
                if ffmpeg.wait() != 0:
                    raise SystemExit("ffmpeg failed")
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()

    print(f"Wrote {args.output} ({duration:.1f}s at {args.fps} fps)")


if __name__ == "__main__":
    main()
