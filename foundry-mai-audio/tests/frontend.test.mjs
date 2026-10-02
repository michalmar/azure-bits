import test from "node:test";
import assert from "node:assert/strict";
import { models, estimatedCost, updateTranscript } from "../static/format.mjs";
test("launch price arithmetic counts Unicode code points", () => {
  assert.equal(estimatedCost("x".repeat(1000000), models[0]), 22);
  assert.equal(estimatedCost("x".repeat(1000000), models[1]), 15);
  assert.equal(estimatedCost("😀", models[0]), 22 / 1e6);
});
test("MAI partial replaces suffix, delta accumulates exactly, completed never duplicates", () => {
  const items = new Map(), type = "conversation.item.input_audio_transcription.";
  const event = (kind, data) => updateTranscript(items, {type: type + kind, item_id: "one", ...data});
  event("delta", {delta: "Hello"});
  event("intermediate", {intermediate: " world"});
  event("intermediate", {intermediate: " there"});
  assert.equal(items.get("one").partial, " there");
  event("delta", {delta: " there!"});
  assert.equal(items.get("one").stable, "Hello there!");
  assert.equal(items.get("one").partial, "");
  event("completed", {transcript: "Hello there!"});
  event("delta", {delta: " late"});
  assert.equal(items.get("one").stable, "Hello there!");
  assert.equal(items.get("one").final, true);
});
