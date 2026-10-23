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

async function loadFrontend({ configOverrides = {}, fetchError, httpStatus = 200 } = {}) {
  class Element {
    constructor() {
      this.value = "";
      this.disabled = true;
      this.dataset = {};
      this.children = [];
      this.attributes = {};
      this.listeners = {};
      this.style = {};
      this.classList = { toggle() {}, add() {}, remove() {} };
    }
    get childElementCount() { return this.children.length; }
    addEventListener(type, listener) { this.listeners[type] = listener; }
    setAttribute(name, value) { this.attributes[name] = value; }
    append(element) { this.children.push(element); }
    focus() { this.focused = true; }
  }
  const elements = new Map();
  const element = (selector) => {
    if (!elements.has(selector)) elements.set(selector, new Element());
    return elements.get(selector);
  };
  const config = {
    model: "gpt-live-1",
    minSessionSeconds: 60,
    maxSessionSeconds: 900,
    defaultSessionSeconds: 300,
    maxInstructionsLength: 12_000,
    defaultPromptId: "default",
    promptPresets: [
      { id: "default", label: "Default", instructions: "Default instructions" },
      { id: "language-tutor", label: "Language tutor", instructions: "Tutor instructions" },
      { id: "grill", label: "Grill", instructions: "Grill instructions" },
    ],
    ...configOverrides,
  };
  const sockets = [];
  class Socket extends Element {
    static OPEN = 1;
    constructor(url) {
      super();
      this.url = url;
      this.sent = [];
      sockets.push(this);
    }
    send(data) { this.sent.push(JSON.parse(data)); }
    close() { return this.listeners.close({ code: 1000 }); }
  }
  const workletUrls = [];
  class Audio {
    state = "running";
    audioWorklet = { addModule: async (url) => workletUrls.push(url.href) };
    destination = {};
    async resume() {}
    async close() { this.state = "closed"; }
    createMediaStreamSource() { return { connect() {} }; }
    createGain() { return { gain: {}, connect() {} }; }
  }
  class Worklet {
    port = { postMessage() {} };
    connect() {}
    disconnect() {}
  }
  let mediaRequests = 0;
  let configRequest;
  let now = 1000;
  const context = vm.createContext({
    document: { querySelector: element, createElement: () => new Element() },
    window: { AudioContext: Audio, AudioWorkletNode: Worklet, addEventListener() {} },
    navigator: {
      mediaDevices: {
        getUserMedia: async () => {
          mediaRequests += 1;
          return { getTracks: () => [{ stop() {} }] };
        },
      },
    },
    location: { protocol: "http:", host: "localhost:8000" },
    WebSocket: Socket,
    AudioContext: Audio,
    AudioWorkletNode: Worklet,
    URL,
    moduleUrl: "http://localhost:8000/assets/test-version/app.js",
    AbortSignal,
    Date: { now: () => now },
    fetch: async (url, options) => {
      configRequest = { url, options };
      if (fetchError) throw fetchError;
      return { ok: httpStatus === 200, status: httpStatus, json: async () => config };
    },
    setInterval: () => 1,
    clearInterval() {},
    setTimeout: () => 2,
    clearTimeout() {},
    canMergeTranscript, clock, decodePcm16, elapsed, transcriptFragment,
  });
  const source = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
  vm.runInContext(source.replace(/^import .+;\n/, "").replaceAll("import.meta.url", "moduleUrl"), context);
  await new Promise(setImmediate);
  return {
    context, config, element, sockets, configRequest, workletUrls, mediaRequests: () => mediaRequests,
    advanceTime(seconds) { now += seconds * 1000; context.updateRemaining(); },
  };
}

test("prompt editor loads the default and preset buttons replace editable text", async () => {
  const { config, element } = await loadFrontend();
  const editor = element("#systemPrompt");
  const buttons = element("#promptPresets").children;
  assert.equal(editor.value, config.promptPresets[0].instructions);
  assert.equal(editor.disabled, false);
  assert.equal(editor.maxLength, config.maxInstructionsLength);
  assert.equal(buttons.length, 3);
  assert.equal(buttons[0].attributes["aria-pressed"], "true");
  for (const [index, button] of buttons.entries()) {
    button.listeners.click();
    assert.equal(editor.value, config.promptPresets[index].instructions);
    assert.equal(button.attributes["aria-pressed"], "true");
    assert.equal(buttons.filter((item) => item.attributes["aria-pressed"] === "true").length, 1);
  }
  editor.value = "My own instructions";
  editor.listeners.input();
  assert.match(element("#promptSelection").textContent, /^Custom prompt/);
  assert.ok(buttons.every((button) => button.attributes["aria-pressed"] === "false"));
  buttons[0].listeners.click();
  assert.equal(editor.value, config.promptPresets[0].instructions);
});

test("conversation sends the exact chosen prompt once and locks it until closed", async () => {
  const { context, element, sockets, workletUrls } = await loadFrontend();
  const editor = element("#systemPrompt");
  const buttons = element("#promptPresets").children;
  editor.value = "  Odpovídej česky.\nAsk one question.  ";
  await context.startConversation();
  assert.equal(workletUrls[0], "http://localhost:8000/assets/test-version/audio-worklet.js");
  assert.equal(editor.disabled, true);
  assert.ok(buttons.every((button) => button.disabled));
  buttons[1].listeners.click();
  assert.equal(editor.value, "  Odpovídej česky.\nAsk one question.  ");
  const socket = sockets[0];
  assert.equal(socket.url, "ws://localhost:8000/api/live");
  assert.equal(socket.sent.length, 0);
  socket.listeners.open();
  assert.equal(socket.sent.length, 1);
  assert.equal(socket.sent[0].type, "start");
  assert.equal(socket.sent[0].instructions, editor.value);
  assert.equal(socket.sent[0].durationSeconds, 300);
  socket.listeners.message({ data: JSON.stringify({ type: "ready", maxSessionSeconds: 300 }) });
  assert.equal(editor.disabled, true);
  assert.equal(element("#sessionButton").textContent, "End conversation");
  context.endConversation();
  assert.equal(editor.disabled, true);
  assert.equal(socket.sent[1].type, "stop");
  await socket.close();
  assert.equal(editor.disabled, false);
  assert.ok(buttons.every((button) => !button.disabled));
  assert.equal(editor.value, "  Odpovídej česky.\nAsk one question.  ");
  await context.startConversation();
  sockets[1].listeners.open();
  assert.equal(sockets[1].sent[0].instructions, editor.value);
});

test("blank or oversized prompts fail before microphone access or a model connection", async () => {
  const { context, config, element, sockets, mediaRequests } = await loadFrontend();
  for (const value of ["", " \n\t ", "x".repeat(config.maxInstructionsLength + 1)]) {
    element("#systemPrompt").value = value;
    await context.startConversation();
    assert.equal(element("#status").dataset.state, "error");
    assert.match(element("#status").textContent, /Enter a system prompt/);
    assert.equal(element("#systemPrompt").disabled, false);
    assert.equal(element("#systemPrompt").focused, true);
  }
  assert.equal(mediaRequests(), 0);
  assert.equal(sockets.length, 0);
});

test("configuration bypasses stale cached responses and has a bounded timeout", async () => {
  const { configRequest } = await loadFrontend();
  assert.equal(configRequest.url, "/api/config");
  assert.equal(configRequest.options.cache, "no-store");
  assert.ok(configRequest.options.signal instanceof AbortSignal);
});

test("configuration failures replace the loading message with an actionable error", async () => {
  for (const options of [
    { httpStatus: 401 },
    { fetchError: new Error("Network request failed.") },
    { fetchError: Object.assign(new Error("Timeout"), { name: "TimeoutError" }) },
    { configOverrides: { promptPresets: undefined } },
    { configOverrides: { promptPresets: [] } },
    { configOverrides: { promptPresets: [{ id: "default", label: "Default" }] } },
    { configOverrides: { maxInstructionsLength: null } },
    { configOverrides: { defaultPromptId: "missing" } },
    { configOverrides: { defaultSessionSeconds: undefined } },
    { configOverrides: { defaultSessionSeconds: 960 } },
    { configOverrides: { minSessionSeconds: 360 } },
    { configOverrides: { maxSessionSeconds: 901 } },
  ]) {
    const { element } = await loadFrontend(options);
    assert.equal(element("#status").dataset.state, "error");
    assert.match(element("#promptSelection").textContent, /could not load.*Reload/);
    assert.equal(element("#systemPrompt").disabled, true);
    assert.equal(element("#sessionButton").disabled, true);
  }
});

test("duration buttons select all whole minutes from 1 to 15 and stop at the bounds", async () => {
  const { element } = await loadFrontend();
  const decrease = element("#decreaseDuration");
  const increase = element("#increaseDuration");
  assert.equal(element("#durationMinutes").textContent, "5 minutes");
  assert.equal(element("#remaining").textContent, "05:00");
  for (let index = 0; index < 20; index += 1) decrease.listeners.click();
  assert.equal(element("#durationMinutes").textContent, "1 minute");
  assert.equal(element("#remaining").textContent, "01:00");
  assert.equal(decrease.disabled, true);
  assert.equal(increase.disabled, false);
  for (let minutes = 2; minutes <= 15; minutes += 1) {
    increase.listeners.click();
    assert.equal(element("#durationMinutes").textContent, `${minutes} minutes`);
    assert.equal(element("#remaining").textContent, `${String(minutes).padStart(2, "0")}:00`);
    assert.equal(element(".session-strip__limit").textContent, `/ ${minutes} minutes per conversation`);
  }
  increase.listeners.click();
  assert.equal(element("#durationMinutes").textContent, "15 minutes");
  assert.equal(increase.disabled, true);
  assert.equal(decrease.disabled, false);
});

test("selected duration is sent once, locked throughout the call, and retained after closing", async () => {
  const { context, element, sockets, advanceTime } = await loadFrontend();
  const increase = element("#increaseDuration");
  const decrease = element("#decreaseDuration");
  for (let index = 0; index < 10; index += 1) increase.listeners.click();
  await context.startConversation();
  assert.equal(decrease.disabled, true);
  assert.equal(increase.disabled, true);
  decrease.listeners.click();
  assert.equal(element("#durationMinutes").textContent, "15 minutes");
  const socket = sockets[0];
  socket.listeners.open();
  assert.equal(socket.sent[0].durationSeconds, 900);
  socket.listeners.message({ data: JSON.stringify({ type: "ready", maxSessionSeconds: 900 }) });
  assert.equal(element("#remaining").textContent, "15:00");
  decrease.listeners.click();
  assert.equal(element("#durationMinutes").textContent, "15 minutes");
  advanceTime(899);
  assert.equal(element("#remaining").textContent, "00:01");
  assert.equal(element("#sessionButton").textContent, "End conversation");
  advanceTime(1);
  assert.equal(element("#remaining").textContent, "00:00");
  assert.match(element("#status").textContent, /^Session time limit reached/);
  assert.equal(decrease.disabled, true);
  await socket.close();
  assert.equal(element("#remaining").textContent, "15:00");
  assert.equal(element("#durationMinutes").textContent, "15 minutes");
  assert.equal(decrease.disabled, false);
  assert.equal(increase.disabled, true);
});
