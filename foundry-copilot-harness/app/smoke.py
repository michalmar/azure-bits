"""Administrative in-container smoke test; all workload calls use managed identity."""

import argparse
import asyncio
import csv
import io
import ipaddress
import json
import os
import socket

from config import Settings
from scenario import REFERENCE
from service import FILE_ID, REPORT_NAMES, HarnessService
from storage import AzureBlobStore


async def check_reports(service, files):
    if len(files) != 3 or any(not FILE_ID.fullmatch(identifier) for identifier in files):
        raise ValueError("Provide exactly three valid Foundry report file IDs")
    downloaded = {}
    for identifier in files:
        metadata = await service.file_client.files.retrieve(identifier)
        name = metadata.filename.rsplit("/", 1)[-1]
        if name not in REPORT_NAMES or name in downloaded:
            raise ValueError("Report names must be budget.json, budget.csv and recommendation.md")
        content = await service.read_file(identifier)
        if not content:
            raise ValueError("Generated report is empty")
        if name == "budget.json" and json.loads(content) != REFERENCE:
            raise ValueError("Downloaded budget does not match the deterministic reference")
        if name == "budget.csv":
            expected = [{
                "id": offer["id"], "base_czk": offer["base_czk"],
                "total_czk": offer["total_czk"], "eligible": str(offer["eligible"]),
                "reasons": ";".join(offer["reasons"]),
            } for offer in REFERENCE["offers"]]
            if list(csv.DictReader(io.StringIO(content.decode()))) != expected:
                raise ValueError("Downloaded CSV does not match the deterministic reference")
        if name == "recommendation.md" and (
            "fiktiv" not in content.decode().casefold() or "Atelier A" not in content.decode()
        ):
            raise ValueError("Recommendation must identify the fictional data and winner")
        downloaded[name] = len(content)
    return downloaded


async def check_storage():
    settings = Settings.from_env()
    addresses = {
        item[4][0] for item in socket.getaddrinfo(settings.storage_account + ".blob.core.windows.net", 443)
    }
    if not addresses or not all(ipaddress.ip_address(value).is_private for value in addresses):
        raise ValueError("Blob DNS must resolve to the existing private endpoint")
    store = AzureBlobStore(settings)
    try:
        for name in ["tokens.css", "baseline.css", "style.css", "app.mjs", "index.html"]:
            properties = await store.container.get_blob_client("copilot-harness/v1/" + name).get_blob_properties()
            if properties.blob_tier != "Cool" or not properties.size:
                raise ValueError("Every published asset must be nonempty and Cool")
    finally:
        await store.close()


async def main(files=None):
    service = HarnessService(
        "https://demo-swe.services.ai.azure.com/api/projects/demo-swe-prj",
        "c631318a-ed22-43fb-b444-f85360564def", "workshop-planner-demo",
        os.environ.get("FOUNDRY_AGENT_VERSION", "1"),
    )
    verified = False
    try:
        if files:
            await check_storage()
            sizes = await check_reports(service, files)
            print(json.dumps({"private_blob_dns": True, "cool_assets": True, "report_bytes": sizes}), flush=True)
            print("FILES_AND_STORAGE_CHECK_PASSED", flush=True)
            return
        async with asyncio.timeout(300):
            async for event in service.run():
                print(json.dumps(event, ensure_ascii=False), flush=True)
                if event["type"] == "result":
                    verified = event["verified"] and not event["warnings"]
                    if verified:
                        await check_reports(service, [file["file_id"] for file in event["files"]])
    finally:
        await service.close()
    if not verified:
        raise SystemExit("Live smoke did not verify every required result")
    print("LIVE_SMOKE_PASSED", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", nargs=3, help="Check existing reports and private assets without another inference run")
    asyncio.run(main(parser.parse_args().files))
