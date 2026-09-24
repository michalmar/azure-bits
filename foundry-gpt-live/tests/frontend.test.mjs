import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

import { canMergeTranscript, clock, decodePcm16, elapsed, transcriptFragment } from "../static/format.mjs";

test("five-minute countdown and overlapping transcript fragments", () => {
  assert.equal(clock(300), "05:00");
  assert.equal(clock(29.1), "00:30");
  assert.equal(clock(-3), "00:00");
  assert.equal(elapsed(200), "00:00");
  const user = transcriptFragment(null, { speaker: "you", text: "Can you", startMs: 200, endMs: 400 });
  const next = { speaker: "you", text: " hear me?", startMs: 400, endMs: 700 };
  assert.equal(canMergeTranscript(user, next), true);
  const continued = transcriptFragment(user, next);
  assert.equal(continued.text, "Can you hear me?");
  assert.equal(continued.startMs, 200);
  const overlap = { speaker: "assistant", text: "Yes", startMs: 500, endMs: 800 };
  assert.equal(canMergeTranscript(continued, overlap), false);
  assert.equal(transcriptFragment(continued, overlap).text, "Yes");
});

test("PCM16 output decoding is signed, little endian, and rejects odd bytes", () => {
  const samples = decodePcm16(Buffer.from([0, 128, 255, 127, 0, 0]).toString("base64"));
  assert.deepEqual(Array.from(samples), [-1, 32767 / 32768, 0]);
  assert.throws(() => decodePcm16("AA=="), /invalid PCM16/);
});

test("microphone resamples 48k to 24k and does not accumulate muted audio", () => {
  let Capture;
  const messages = [];
  const source = readFileSync(new URL("../static/audio-worklet.js", import.meta.url), "utf8");
  vm.runInNewContext(source, {
    sampleRate: 48000,
    AudioWorkletProcessor: class {
      constructor() {
        this.port = { postMessage: (message) => messages.push(message), onmessage: null };
      }
    },
    registerProcessor: (name, implementation) => {
      assert.equal(name, "pcm-capture");
      Capture = implementation;
    },
  });
  const capture = new Capture();
  const frame = [new Float32Array(128).fill(0.25)];
  for (let index = 0; index < 38; index += 1) capture.process([frame]);
  const sent = messages.filter((message) => message.type === "audio");
  assert.equal(sent.length, 5);
  assert.equal(sent[0].buffer.byteLength, 960);
  capture.port.onmessage({ data: { type: "mute", muted: true } });
  for (let index = 0; index < 750; index += 1) capture.process([frame]);
  assert.equal(messages.filter((message) => message.type === "audio").length, 5);
  capture.port.onmessage({ data: { type: "mute", muted: false } });
  capture.process([frame]);
  assert.ok(capture.samples.length < 480);
});
