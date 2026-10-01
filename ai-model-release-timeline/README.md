# AI model release timeline

A deterministic, animated comparison of public OpenAI and Anthropic model
releases from October 2024 through September 2026. The browser player and MP4
exporter use the same canvas renderer, so a timestamp always produces the same
1920 × 1080 frame.

## What the demo shows

- releases from both labs on one shared date axis;
- major generation changes and model-family eras;
- synchronized same-day launches;
- cumulative release counts and quarterly cadence;
- an interactive play, pause, restart, and scrub experience;
- a downloadable 1080p MP4 and poster frame.

Release dates, notes, and source URLs live in
[`static/releases.json`](static/releases.json). Dates represent first public
availability rather than an earlier private preview unless the note says
otherwise. The dataset is current through October 1, 2026.

## Prerequisites

- Python 3.11 or later
- Chromium installed through Playwright

No Azure resources, credentials, backend, or API keys are required.

## Run locally

```bash
cd ai-model-release-timeline
python -m http.server 8000
```

Open <http://localhost:8000/static/>. Serving the demo folder rather than only
`static/` also makes the downloadable MP4 available to the player.

## Install export and test dependencies

```bash
cd ai-model-release-timeline
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Render the media

The exporter starts an ephemeral local server, asks the deterministic renderer
for each frame, and pipes PNG frames to ffmpeg:

```bash
python scripts/render_video.py
```

Outputs:

- `media/model-release-timeline.mp4`
- `media/poster.png`

Render selected PNG frames without producing a video:

```bash
python scripts/render_video.py --stills 0 20 40 65 75
```

Use `--fps` to choose another frame rate or `--output` and `--poster` to choose
different output paths.

## Validate

```bash
pytest -q
```

The tests verify chronological ordering, timeline bounds, source URL shape,
continuous era coverage, and required player/export assets.

## Project structure

```text
ai-model-release-timeline/
├── media/                  # Generated MP4 and poster
├── scripts/
│   └── render_video.py     # Playwright + ffmpeg exporter
├── static/
│   ├── index.html          # Interactive player
│   ├── player.js           # Playback controls
│   ├── releases.json       # Timeline data and sources
│   ├── render.html         # Minimal export-only page
│   ├── styles.css          # Demo-specific player styles
│   └── timeline.js         # Deterministic canvas renderer
└── tests/
    └── test_data.py
```
