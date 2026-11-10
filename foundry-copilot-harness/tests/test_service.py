import pytest

from service import public_url, response_content, tool_event


def test_tool_events_exclude_reasoning_and_arguments():
    assert tool_event({"type": "response.reasoning_text.delta", "delta": "private"}) is None
    assert tool_event({"type": "response.function_call_arguments.delta", "delta": "private"}) is None
    event = tool_event({"type": "response.output_item.added", "item": {
        "type": "function_call", "name": "skill", "arguments": "private", "id": "tool-1",
    }})
    assert event == {"type": "tool", "id": "tool-1", "name": "skill", "status": "started"}


def test_content_annotations():
    text, citations, files = response_content([{"type": "message", "content": [{
        "type": "output_text", "text": "<script>untrusted</script>",
        "annotations": [
            {"type": "url_citation", "url": "https://example.com", "title": "Advice"},
            {"type": "url_citation", "url": "javascript:alert(1)"},
            {"type": "file_path", "file_id": "file-1", "filename": "budget.json"},
            {"type": "file_path", "file_id": "file-2", "filename": "secret.txt"},
        ],
    }]}])
    assert text == "<script>untrusted</script>"
    assert citations == [{"url": "https://example.com", "title": "Advice"}]
    assert files == [{"file_id": "file-1", "filename": "budget.json"}]


def test_file_path_without_filename_is_resolved_from_file_metadata():
    _, _, files = response_content([{"type": "message", "content": [{
        "type": "output_text", "text": "Download",
        "annotations": [{"type": "file_path", "file_id": "file-1", "index": 0}],
    }]}])
    assert files == [{"file_id": "file-1", "filename": ""}]


@pytest.mark.parametrize("url", ["http://example.com", "https://user:pass@example.com", "https://x/\nsecret", "javascript:x", None])
def test_invalid_citation_url(url):
    assert public_url(url) is None
