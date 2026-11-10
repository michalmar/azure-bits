import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { describeTool, readEvents, safeURL } from "../static/app.mjs";

test("NDJSON handles split UTF-8 bytes and partial lines", async () => {
  const bytes = new TextEncoder().encode('{"type":"text","text":"Příliš"}\n{"type":"result"}\n');
  const stream = new ReadableStream({
    start(controller) {
      for (let i = 0; i < bytes.length; i += 3) controller.enqueue(bytes.slice(i, i + 3));
      controller.close();
    },
  });
  const results = [];
  for await (const event of readEvents(stream)) results.push(event);
  assert.deepEqual(results, [{ type: "text", text: "Příliš" }, { type: "result" }]);
});

test("reject unsafe citations", () => {
  for (const url of ["javascript:alert(1)", "data:text/html,test", "https://user:pass@example.com", "/local"]) {
    assert.equal(safeURL(url), null);
  }
  assert.equal(safeURL("https://example.com/advice"), "https://example.com/advice");
});

test("describeTool maps harness tool names and lifecycle states", () => {
  const started = describeTool("web_search_call", "started");
  assert.equal(started.canonical, "web_search");
  assert.equal(started.state, "running");
  assert.equal(started.statusText, "Probíhá…");

  const searching = describeTool("web_search", "searching");
  assert.equal(searching.state, "running");
  assert.equal(searching.statusText, "Vyhledává na webu…");

  const completed = describeTool("upload_file_from_workspace_to_foundry_project", "completed");
  assert.equal(completed.state, "completed");
  assert.equal(completed.statusText, "Hotovo");
});

test("model output is rendered via safe DOM nodes, never raw HTML", async () => {
  const source = await readFile(new URL("../static/app.mjs", import.meta.url), "utf8");
  assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|eval\(/);
  assert.match(source, /renderMarkdown\(document,\s*event\.text\)/);
});
