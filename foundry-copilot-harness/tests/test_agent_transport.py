import base64
import json
from types import SimpleNamespace

import pytest

from scenario import OFFERS, REFERENCE
from service import HarnessService


class Event:
    def __init__(self, value):
        self.value = value

    def model_dump(self, **kwargs):
        return self.value


class Stream:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def __aiter__(self):
        for event in self.events:
            yield Event(event)


def fake_service(events, *, version="1"):
    calls = {"create": [], "delete": []}

    async def get_agent(name):
        return SimpleNamespace(as_dict=lambda: {
            "versions": {"latest": {"version": version, "definition": {
                "harness": {"type": "microsoft_copilot_preview"},
                "skills": [{"name": "workshop-planner", "version": "2"}],
            }}},
        })

    async def conversation():
        return SimpleNamespace(id="conv-test")

    async def create(**kwargs):
        calls["create"].append(kwargs)
        return Stream(events)

    async def delete(identifier):
        calls["delete"].append(identifier)

    async def metadata(identifier):
        filenames = {
            "file-budget-json": "budget.json",
            "file-budget-csv": "budget.csv",
            "file-recommendation-md": "recommendation.md",
        }
        return SimpleNamespace(filename=filenames[identifier])

    async def read_file(identifier):
        return json.dumps(REFERENCE).encode()

    service = object.__new__(HarnessService)
    service.agent, service.version = "workshop-planner-demo", "1"
    service.project = SimpleNamespace(agents=SimpleNamespace(get=get_agent))
    service.client = SimpleNamespace(
        conversations=SimpleNamespace(create=conversation, delete=delete),
        responses=SimpleNamespace(create=create),
    )
    service.file_client = SimpleNamespace(files=SimpleNamespace(retrieve=metadata))
    service.read_file = read_file
    return service, calls


def complete_events():
    tools = [
        {"type": "response.output_item.added", "item": {"type": "function_call", "name": name}}
        for name in ["skill", "view"]
    ] + [
        {"type": "response.output_item.added", "item": {"type": "shell_call"}},
        {"type": "response.web_search_call.completed", "item_id": "web-test"},
    ]
    return tools + [{"type": "response.completed", "response": {
        "id": "response-test", "status": "completed", "output": [{
            "type": "message", "content": [{
                "type": "output_text", "text": "Doporučení A",
                "annotations": [
                    {"type": "file_path", "file_id": identifier}
                    for identifier in ["file-budget-json", "file-budget-csv", "file-recommendation-md"]
                ] + [{"type": "url_citation", "url": "https://example.com/advice"}],
            }],
        }],
    }}]


@pytest.mark.asyncio
async def test_real_transport_shape_and_verification():
    service, calls = fake_service(complete_events())
    events = [event async for event in service.run()]
    result = events[-1]
    assert result["type"] == "result" and result["verified"] is True
    assert result["warnings"] == []
    assert result["budget"] == REFERENCE and len(result["files"]) == 3
    assert calls["delete"] == ["conv-test"]
    request = calls["create"][0]
    assert set(request) == {"conversation", "input", "stream"}
    assert request["conversation"] == "conv-test"
    file = request["input"][0]["content"][1]
    assert base64.b64decode(file["file_data"].split(",", 1)[1]) == OFFERS


@pytest.mark.asyncio
async def test_stream_without_terminal_event_is_failure():
    service, calls = fake_service([])
    events = [event async for event in service.run()]
    assert events[-1]["type"] == "error"
    assert calls["delete"] == ["conv-test"]


@pytest.mark.asyncio
async def test_version_change_does_not_invoke():
    service, calls = fake_service([], version="2")
    with pytest.raises(ValueError, match="version changed"):
        _ = [event async for event in service.run()]
    assert calls["create"] == [] and calls["delete"] == []


@pytest.mark.asyncio
async def test_generator_close_cleans_up_conversation():
    service, calls = fake_service([])
    generator = service.run()
    assert (await anext(generator))["type"] == "accepted"
    await generator.aclose()
    assert calls["delete"] == ["conv-test"]


@pytest.mark.asyncio
async def test_bad_budget_never_presented_as_verified():
    service, _ = fake_service(complete_events())

    async def bad_file(identifier):
        return b'{"winner":"B"}'

    service.read_file = bad_file
    events = [event async for event in service.run()]
    assert events[-1]["verified"] is False
    assert events[-1]["budget"] is None
    assert events[-1]["warnings"]
