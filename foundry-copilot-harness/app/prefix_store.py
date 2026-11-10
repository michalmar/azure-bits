"""Confine the bundled publisher and reader to this demo's asset prefix."""

from storage import AzureBlobStore, BlobInfo

PREFIX = "copilot-harness/v1/"


class PrefixBlobStore(AzureBlobStore):
    async def stat(self, path):
        info = await super().stat(PREFIX + path)
        return BlobInfo(path, info.size, info.content_type, info.etag)

    async def download(self, path, offset, length, etag):
        return await super().download(PREFIX + path, offset, length, etag)

    async def stage(self, path, block_id, data):
        return await super().stage(PREFIX + path, block_id, data)

    async def commit(self, path, block_ids, content_type, condition):
        return await super().commit(PREFIX + path, block_ids, content_type, condition)

    async def delete(self, path, condition):
        return await super().delete(PREFIX + path, condition)

    async def list(self, prefix, marker):
        items, marker = await super().list(PREFIX + prefix, marker)
        return [
            BlobInfo(info.path.removeprefix(PREFIX), info.size, info.content_type, info.etag)
            for info in items
        ], marker
