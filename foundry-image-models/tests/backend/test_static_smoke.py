from __future__ import annotations

from app.service import FoundryService
from tests.backend.helpers import make_client


def test_root_and_static_asset_are_served():
    service = FoundryService(credential=object())

    with make_client(service) as client:
        root = client.get("/")
        asset = client.get("/static/styles.css")

    assert root.status_code == 200
    assert "Microsoft Foundry" in root.text
    assert asset.status_code == 200
    assert asset.headers["content-type"].startswith("text/css")
