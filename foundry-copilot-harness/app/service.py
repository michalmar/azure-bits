"""Transport only: the agent loop, tools and sandbox are operated by Foundry."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
import json
import logging
import re
from urllib.parse import urlsplit

import anyio
from azure.ai.projects.aio import AIProjectClient
from azure.identity.aio import ManagedIdentityCredential
from openai import APIError

from scenario import OFFERS, PROMPT, REFERENCE

logger = logging.getLogger("workshop")
FILE_ID = re.compile(r"[A-Za-z0-9_-]{1,200}")
REPORT_NAMES = {"budget.json", "budget.csv", "recommendation.md"}
MAX_REPORT_BYTES = 2 * 1024 * 1024


def public_url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme == "https" and parsed.hostname and not parsed.username
            and not parsed.password and not any(ord(c) < 33 for c in value)
        ):
            return value
    except ValueError:
        return None
    return None


def response_content(output: list[dict]) -> tuple[str, list[dict], list[dict]]:
    texts, citations, files = [], {}, {}
    for item in output:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") != "output_text":
                continue
            texts.append(content.get("text", ""))
            for annotation in content.get("annotations", []):
                url = public_url(annotation.get("url"))
                if annotation.get("type") == "url_citation" and url:
                    citations[url] = {"url": url, "title": str(annotation.get("title", url))[:300]}
                identifier = annotation.get("file_id")
                filename = str(annotation.get("filename", "")).rsplit("/", 1)[-1]
                if (
                    annotation.get("type") in {"file_path", "container_file_citation", "file_citation"}
                    and isinstance(identifier, str) and FILE_ID.fullmatch(identifier)
                    and (not filename or filename in REPORT_NAMES)
                ):
                    files[identifier] = {"file_id": identifier, "filename": filename}
    return "\n\n".join(texts), list(citations.values()), list(files.values())


def tool_event(event: dict) -> dict | None:
    kind = event.get("type", "")
    if kind in {"response.output_item.added", "response.output_item.done"}:
        item = event.get("item", {})
        item_type = item.get("type", "")
        if item_type.endswith("_call"):
            return {
                "type": "tool", "id": item.get("id", ""),
                "name": item.get("name") or item_type,
                "status": "completed" if kind.endswith(".done") else "started",
            }
    if kind.startswith("response.web_search_call."):
        return {
            "type": "tool", "id": event.get("item_id", ""), "name": "web_search",
            "status": kind.rsplit(".", 1)[-1],
        }
    return None


class HarnessService:
    def __init__(self, endpoint: str, identity: str, agent: str, version: str):
        if (
            not endpoint.startswith("https://") or not endpoint.endswith("/api/projects/demo-swe-prj")
            or agent != "workshop-planner-demo" or not version.isdigit()
        ):
            raise ValueError("Configure the approved project, agent name and numeric version")
        self.credential = ManagedIdentityCredential(client_id=identity)
        self.project = AIProjectClient(endpoint, self.credential, allow_preview=True)
        self.client = self.project.get_openai_client(agent_name=agent, max_retries=0, timeout=300)
        self.file_client = self.project.get_openai_client(max_retries=0, timeout=30)
        self.agent, self.version = agent, version

    async def close(self):
        try:
            await self.client.close()
            await self.file_client.close()
            await self.project.close()
        finally:
            await self.credential.close()

    async def read_file(self, identifier: str) -> bytes:
        content = bytearray()
        async with asyncio.timeout(30):
            async with self.file_client.files.with_streaming_response.content(identifier) as response:
                async for chunk in response.iter_bytes():
                    if len(content) + len(chunk) > MAX_REPORT_BYTES:
                        raise ValueError("Generated report exceeds the download limit")
                    content.extend(chunk)
        return bytes(content)

    async def run(self) -> AsyncIterator[dict]:
        conversation_id = None
        completed = False
        observed_tools = set()
        try:
            agent = (await self.project.agents.get(self.agent)).as_dict()
            latest = agent["versions"]["latest"]
            if latest["version"] != self.version:
                raise ValueError("Active agent version changed; redeploy the app with the reviewed version")
            definition = latest["definition"]
            if definition.get("harness", {}).get("type") != "microsoft_copilot_preview":
                raise ValueError("The deployed agent does not use the Copilot harness")
            conversation = await self.client.conversations.create()
            conversation_id = conversation.id
            yield {
                "type": "accepted", "conversation_id": conversation_id,
                "agent": self.agent, "agent_version": self.version,
                "skills": definition.get("skills", []),
            }
            stream = await self.client.responses.create(
                conversation=conversation_id,
                input=[{"role": "user", "content": [
                    {"type": "input_text", "text": PROMPT},
                    {"type": "input_file", "filename": "offers.csv",
                     "file_data": "data:text/csv;base64," + base64.b64encode(OFFERS).decode("ascii")},
                ]}],
                stream=True,
            )
            async with stream:
                async for value in stream:
                    event = value.model_dump(mode="json", exclude_none=True)
                    observed = tool_event(event)
                    if observed:
                        observed_tools.add(observed["name"])
                        yield observed
                    if event["type"] == "response.output_text.delta":
                        yield {"type": "text", "text": event["delta"]}
                    if event["type"] in {"response.failed", "response.incomplete", "error"}:
                        logger.warning("agent_response_failure type=%s", event["type"])
                        yield {
                            "type": "error",
                            "message": "Foundry nedokončilo odpověď. Výsledek není ověřený.",
                        }
                        return
                    if event["type"] == "response.completed":
                        response = event["response"]
                        if response.get("status") != "completed":
                            raise ValueError("Response completed event has no completed status")
                        text, citations, files = response_content(response.get("output", []))
                        resolved_files = []
                        for file in files:
                            if not file["filename"]:
                                metadata = await self.file_client.files.retrieve(file["file_id"])
                                file["filename"] = metadata.filename.rsplit("/", 1)[-1]
                            if file["filename"] in REPORT_NAMES:
                                resolved_files.append(file)
                        files = resolved_files
                        verified = False
                        warnings = []
                        required_tools = {"skill", "view", "shell_call"}
                        if not required_tools.issubset(observed_tools):
                            warnings.append("Stream nedoložil všechny požadované nástroje skill/view/shell; ověřte Foundry trace.")
                        if not observed_tools.intersection({"web_search", "web_search_call"}):
                            warnings.append("Stream nedoložil web search.")
                        for file in files:
                            if file["filename"] == "budget.json":
                                result = json.loads(await self.read_file(file["file_id"]))
                                verified = result == REFERENCE
                                if not verified:
                                    warnings.append("Rozpočet agenta neodpovídá kontrolnímu výpočtu.")
                        if not verified:
                            warnings.append("Chybí ověřený budget.json; neprezentujeme rozpočet jako ověřený.")
                        if not citations:
                            warnings.append("Odpověď nemá strojově dostupné webové citace.")
                        if len({file["filename"] for file in files}) < 3:
                            warnings.append("Foundry nevrátilo všechny tři soubory ke stažení.")
                        completed = True
                        yield {
                            "type": "result", "response_id": response["id"],
                            "conversation_id": conversation_id, "text": text,
                            "citations": citations, "files": files, "verified": verified,
                            "budget": REFERENCE if verified else None, "warnings": warnings,
                            "observed_tools": sorted(observed_tools),
                            "usage": response.get("usage"),
                        }
            if not completed:
                yield {"type": "error", "message": "Stream skončil bez dokončené odpovědi. Vzdálený stav není potvrzen."}
        finally:
            if conversation_id:
                try:
                    with anyio.CancelScope(shield=True):
                        async with asyncio.timeout(20):
                            await self.client.conversations.delete(conversation_id)
                except (APIError, TimeoutError) as exc:
                    logger.warning(
                        "conversation_cleanup_failed conversation=%s type=%s completed=%s",
                        conversation_id, type(exc).__name__, completed,
                    )
                    # Preserve cancellation; a disconnected browser cannot receive this notice.
                    # The warning and conversation ID remain in application logs for cleanup.
