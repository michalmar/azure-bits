import pytest

from prefix_store import PREFIX, PrefixBlobStore
from storage import AzureBlobStore, BlobInfo


@pytest.mark.asyncio
async def test_storage_never_touches_audio_prefix(monkeypatch):
    calls = []

    async def stat(self, path):
        calls.append(path)
        return BlobInfo(path, 42, "text/html", '"etag"')

    async def stage(self, path, block_id, data):
        calls.append(path)

    async def listing(self, prefix, marker):
        calls.append(prefix)
        return [BlobInfo(prefix + "index.html", 42, "text/html", '"etag"')], None

    monkeypatch.setattr(AzureBlobStore, "stat", stat)
    monkeypatch.setattr(AzureBlobStore, "stage", stage)
    monkeypatch.setattr(AzureBlobStore, "list", listing)
    store = object.__new__(PrefixBlobStore)
    assert (await store.stat("index.html")).path == "index.html"
    await store.stage("style.css", "block", b"css")
    entries, _ = await store.list("", None)
    assert entries[0].path == "index.html"
    assert calls == [PREFIX + "index.html", PREFIX + "style.css", PREFIX]
