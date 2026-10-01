import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse


DEMO_DIR = Path(__file__).resolve().parent.parent
DATA = json.loads((DEMO_DIR / "static" / "releases.json").read_text())


def test_release_dates_are_sorted_and_inside_window() -> None:
    start = date.fromisoformat(DATA["window"]["start"])
    end = date.fromisoformat(DATA["window"]["end"])
    release_dates = [date.fromisoformat(release["date"]) for release in DATA["releases"]]

    assert release_dates == sorted(release_dates)
    assert all(start <= release_date <= end for release_date in release_dates)


def test_releases_have_supported_labs_and_sources() -> None:
    labs = set(DATA["labs"])

    for release in DATA["releases"]:
        assert release["lab"] in labs
        assert release["name"].strip()
        assert release["note"].strip()
        source = urlparse(release["source"])
        assert source.scheme == "https"
        assert source.netloc


def test_lab_eras_cover_the_full_window_without_gaps() -> None:
    window_start = date.fromisoformat(DATA["window"]["start"])
    window_end = date.fromisoformat(DATA["window"]["end"])

    for lab in DATA["labs"].values():
        eras = lab["eras"]
        assert date.fromisoformat(eras[0]["start"]) == window_start
        assert date.fromisoformat(eras[-1]["end"]) == window_end
        for current, following in zip(eras, eras[1:]):
            current_end = date.fromisoformat(current["end"])
            following_start = date.fromisoformat(following["start"])
            assert (following_start - current_end).days == 1


def test_player_and_exporter_assets_exist() -> None:
    expected = [
        "static/index.html",
        "static/player.js",
        "static/render.html",
        "static/timeline.js",
        "scripts/render_video.py",
    ]

    assert all((DEMO_DIR / path).is_file() for path in expected)
