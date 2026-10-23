import { canMergeTranscript, clock, decodePcm16, elapsed, transcriptFragment } from "./format.mjs";

const status = document.querySelector("#status");
const remaining = document.querySelector("#remaining");
const sessionButton = document.querySelector("#sessionButton");
const muteButton = document.querySelector("#muteButton");
const clearButton = document.querySelector("#clearButton");
const transcriptList = document.querySelector("#transcriptList");
const emptyState = document.querySelector("#emptyState");
const micLevel = document.querySelector("#micLevel");
const modelLevel = document.querySelector("#modelLevel");
const micState = document.querySelector("#micState");
const modelState = document.querySelector("#modelState");
const modelName = document.querySelector("#modelName");
const systemPrompt = document.querySelector("#systemPrompt");
const promptPresets = document.querySelector("#promptPresets");
const promptSelection = document.querySelector("#promptSelection");
const durationMinutes = document.querySelector("#durationMinutes");
const decreaseDuration = document.querySelector("#decreaseDuration");
const increaseDuration = document.querySelector("#increaseDuration");

let socket;
let microphone;
let captureContext;
let playbackContext;
let captureNode;
let phase = "idle";
let muted = false;
let config;
let selectedSessionSeconds;
let deadline;
let timer;
let closeTimer;
let nextAudioAt = 0;
let lastFragment;
const activeSources = new Set();

function setStatus(message, state = "") {
  status.textContent = message;
  status.dataset.state = state;
}

function updatePromptSelection() {
  const selected = config.promptPresets.find((preset) => preset.instructions === systemPrompt.value);
  for (const button of promptPresets.children) {
    button.setAttribute("aria-pressed", String(button.dataset.presetId === selected?.id));
  }
  promptSelection.textContent =
    `${selected ? `${selected.label} preset` : "Custom prompt"} · ${systemPrompt.value.length} / ${config.maxInstructionsLength} characters`;
}

function updateDurationControls() {
  const editable = config && phase === "idle";
  decreaseDuration.disabled = !editable || selectedSessionSeconds <= config.minSessionSeconds;
  increaseDuration.disabled = !editable || selectedSessionSeconds >= config.maxSessionSeconds;
  if (!config) return;
  const minutes = selectedSessionSeconds / 60;
  const label = `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
  durationMinutes.textContent = label;
  document.querySelector(".session-strip__limit").textContent = `/ ${label} per conversation`;
  if (phase === "idle") remaining.textContent = clock(selectedSessionSeconds);
}

function changeDuration(delta) {
  if (!config || phase !== "idle") return;
  selectedSessionSeconds = Math.min(
    config.maxSessionSeconds, Math.max(config.minSessionSeconds, selectedSessionSeconds + delta),
  );
  updateDurationControls();
}

function updateRemaining() {
  if (!deadline) return;
  const seconds = Math.max(0, (deadline - Date.now()) / 1000);
  remaining.textContent = clock(seconds);
  remaining.classList.toggle("is-low", seconds <= 30);
  if (seconds <= 0 && phase === "active") {
    setPhase("ending");
    setStatus("Session time limit reached. Closing the conversation…");
  }
}

function setPhase(next) {
  phase = next;
  const active = next === "active";
  const idle = next === "idle";
  sessionButton.textContent = active ? "End conversation" : "Start conversation";
  sessionButton.classList.toggle("is-active", active);
  sessionButton.disabled = !config || (!active && !idle);
  muteButton.disabled = !active;
  clearButton.disabled = !idle || !transcriptList.childElementCount;
  systemPrompt.disabled = !config || !idle;
  for (const button of promptPresets.children) button.disabled = !config || !idle;
  updateDurationControls();
  micState.textContent = active ? (muted ? "Muted" : "Live") : "Off";
  modelState.textContent = active ? "Live" : "Off";
  if (!active) {
    micLevel.style.transform = "scaleX(0)";
    modelLevel.style.transform = "scaleX(0)";
  }
}

function addTranscript(event) {
  if (!event.text) return;
  emptyState.hidden = true;
  const merge = canMergeTranscript(lastFragment, event);
  const next = transcriptFragment(lastFragment, event);
  const previous = transcriptList.lastElementChild;
  if (merge && previous) {
    previous.querySelector(".transcript__text").textContent = next.text;
  } else {
    const row = document.createElement("li");
    row.className = "transcript__item";
    row.dataset.speaker = event.speaker;
    const label = document.createElement("span");
    label.className = "transcript__speaker";
    const speaker = document.createElement("span");
    speaker.textContent = event.speaker === "you" ? "You" : "GPT-Live";
    const time = document.createElement("time");
    time.textContent = elapsed(event.startMs);
    label.append(speaker, time);
    const text = document.createElement("p");
    text.className = "transcript__text";
    text.textContent = next.text;
    row.append(label, text);
    transcriptList.append(row);
  }
  lastFragment = next;
  transcriptList.lastElementChild.scrollIntoView({ block: "nearest" });
}

function playPcm(data) {
  if (!playbackContext || playbackContext.state === "closed") return;
  const samples = decodePcm16(data);
  const buffer = playbackContext.createBuffer(1, samples.length, 24000);
  buffer.getChannelData(0).set(samples);
  const source = playbackContext.createBufferSource();
  source.buffer = buffer;
  source.connect(playbackContext.destination);
  const now = playbackContext.currentTime;
  if (nextAudioAt - now > 0.6) throw new Error("Audio playback fell behind. Start a new conversation.");
  const playAt = Math.max(now + 0.02, nextAudioAt);
  source.start(playAt);
  nextAudioAt = playAt + buffer.duration;
  activeSources.add(source);
  const level = Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length);
  modelLevel.style.transform = `scaleX(${Math.min(1, level * 5)})`;
  source.addEventListener("ended", () => {
    activeSources.delete(source);
    if (!activeSources.size) modelLevel.style.transform = "scaleX(0)";
  }, { once: true });
}

async function releaseMedia() {
  clearInterval(timer);
  clearTimeout(closeTimer);
  timer = null;
  closeTimer = null;
  deadline = null;
  remaining.textContent = clock(selectedSessionSeconds);
  remaining.classList.remove("is-low");
  captureNode?.disconnect();
  captureNode = null;
  microphone?.getTracks().forEach((track) => track.stop());
  microphone = null;
  if (captureContext && captureContext.state !== "closed") await captureContext.close();
  captureContext = null;
  activeSources.forEach((source) => {
    try {
      source.stop();
    } catch (error) {
      if (error.name !== "InvalidStateError") throw error;
    }
  });
  activeSources.clear();
  if (playbackContext && playbackContext.state !== "closed") await playbackContext.close();
  playbackContext = null;
  nextAudioAt = 0;
  muted = false;
  muteButton.textContent = "Mute microphone";
}

function onMessage(event) {
  let message;
  try {
    message = JSON.parse(event.data);
    if (message.type === "ready") {
      deadline = Date.now() + message.maxSessionSeconds * 1000;
      updateRemaining();
      timer = setInterval(updateRemaining, 250);
      setPhase("active");
      setStatus("Conversation live. Speak any time, including while the model speaks.", "active");
    } else if (message.type === "transcript") {
      addTranscript(message);
    } else if (message.type === "audio") {
      playPcm(message.data);
    } else if (message.type === "muted") {
      micState.textContent = message.muted ? "Muted" : "Live";
    } else if (message.type === "notice") {
      setStatus(message.message);
    } else if (message.type === "limit") {
      setStatus(message.message);
    } else if (message.type === "error") {
      setStatus(message.message, "error");
      setPhase("ending");
      socket?.close();
    } else if (message.type === "closed") {
      setStatus(
        message.reason === "expired" || remaining.textContent === "00:00"
          ? "Session time limit reached. Start a new conversation."
          : "Conversation ended. Start a new conversation.",
      );
      setPhase("ending");
      socket?.close();
    }
  } catch (error) {
    setStatus(`Conversation failed: ${error.message}`, "error");
    setPhase("ending");
    socket?.close();
  }
}

async function startConversation() {
  const instructions = systemPrompt.value;
  const durationSeconds = selectedSessionSeconds;
  if (!instructions.trim() || instructions.length > config.maxInstructionsLength) {
    setStatus(`Enter a system prompt of 1 to ${config.maxInstructionsLength} characters.`, "error");
    systemPrompt.focus();
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode || !window.AudioContext) {
    setStatus("This browser needs microphone and AudioWorklet support. Try a current browser over HTTPS.", "error");
    return;
  }
  setPhase("connecting");
  setStatus("Requesting microphone access…");
  try {
    playbackContext = new AudioContext();
    await playbackContext.resume();
    microphone = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    captureContext = new AudioContext();
    await captureContext.audioWorklet.addModule(new URL("./audio-worklet.js", import.meta.url));
    const source = captureContext.createMediaStreamSource(microphone);
    captureNode = new AudioWorkletNode(captureContext, "pcm-capture");
    captureNode.port.onmessage = ({ data }) => {
      if (data.type === "level") {
        micLevel.style.transform = `scaleX(${data.value})`;
      } else if (data.type === "audio" && phase === "active" && !muted && socket?.readyState === WebSocket.OPEN) {
        if (socket.bufferedAmount > 96_000) {
          endConversation("Microphone upload fell behind. Start a new conversation.");
          return;
        }
        socket.send(data.buffer);
      }
    };
    source.connect(captureNode);
    const silent = captureContext.createGain();
    silent.gain.value = 0;
    captureNode.connect(silent);
    silent.connect(captureContext.destination);
    await captureContext.resume();

    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const current = new WebSocket(`${scheme}://${location.host}/api/live`);
    socket = current;
    current.addEventListener("message", onMessage);
    current.addEventListener("open", () => {
      current.send(JSON.stringify({ type: "start", instructions, durationSeconds }));
      setStatus("Waiting for GPT-Live…");
    });
    current.addEventListener("close", async (event) => {
      if (socket !== current) return;
      socket = null;
      const unexpected = phase === "active" || phase === "connecting";
      await releaseMedia();
      setPhase("idle");
      if (unexpected) {
        const detail = event.code === 4429
          ? "The demo is at its concurrent session limit. Try again shortly."
          : event.code === 4401
            ? "Sign-in expired. Reload the page to sign in again."
            : "The connection ended before the conversation finished. Start again.";
        setStatus(detail, "error");
      }
    });
  } catch (error) {
    setStatus(`Microphone could not start: ${error.message}`, "error");
    socket?.close();
    await releaseMedia();
    setPhase("idle");
  }
}

function endConversation(errorMessage = "") {
  if (phase !== "active") return;
  setPhase("ending");
  setStatus(errorMessage || "Ending conversation…", errorMessage ? "error" : "");
  captureNode?.port.postMessage({ type: "mute", muted: true });
  socket.send(JSON.stringify({ type: "stop" }));
  closeTimer = setTimeout(() => {
    setStatus("The model did not confirm the end of the session. Connection closed.", "error");
    socket?.close();
  }, 12_000);
}

sessionButton.addEventListener("click", () => {
  if (phase === "active") endConversation();
  else if (phase === "idle") void startConversation();
});

muteButton.addEventListener("click", () => {
  if (phase !== "active") return;
  muted = !muted;
  captureNode.port.postMessage({ type: "mute", muted });
  socket.send(JSON.stringify({ type: "mute", muted }));
  muteButton.textContent = muted ? "Unmute microphone" : "Mute microphone";
  micState.textContent = muted ? "Muted" : "Live";
  if (muted) micLevel.style.transform = "scaleX(0)";
});

clearButton.addEventListener("click", () => {
  transcriptList.replaceChildren();
  lastFragment = null;
  emptyState.hidden = false;
  clearButton.disabled = true;
  setStatus("Transcript cleared from this tab.");
});

systemPrompt.addEventListener("input", updatePromptSelection);
decreaseDuration.addEventListener("click", () => changeDuration(-60));
increaseDuration.addEventListener("click", () => changeDuration(60));

window.addEventListener("pagehide", () => {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "stop" }));
  socket?.close();
  microphone?.getTracks().forEach((track) => track.stop());
});

fetch("/api/config", { cache: "no-store", signal: AbortSignal.timeout(15_000) })
  .then((response) => {
    if (!response.ok) throw new Error(`Configuration request failed (HTTP ${response.status}).`);
    return response.json();
  })
  .then((value) => {
    if (
      !Array.isArray(value?.promptPresets)
      || !value.promptPresets.length
      || !value.promptPresets.every((preset) =>
        typeof preset?.id === "string"
        && typeof preset.label === "string"
        && typeof preset.instructions === "string")
      || !Number.isInteger(value.maxInstructionsLength)
      || value.maxInstructionsLength < 1
      || ![value.minSessionSeconds, value.maxSessionSeconds, value.defaultSessionSeconds]
        .every((seconds) => Number.isInteger(seconds) && seconds > 0 && seconds % 60 === 0)
      || value.minSessionSeconds > value.defaultSessionSeconds
      || value.defaultSessionSeconds > value.maxSessionSeconds
    ) {
      throw new Error("The server returned incompatible conversation settings. Reload the page to try again.");
    }
    const defaultPreset = value.promptPresets.find((preset) => preset.id === value.defaultPromptId);
    if (!defaultPreset) {
      throw new Error("The server did not provide a default prompt. Reload the page to try again.");
    }
    config = value;
    selectedSessionSeconds = value.defaultSessionSeconds;
    systemPrompt.maxLength = value.maxInstructionsLength;
    systemPrompt.value = defaultPreset.instructions;
    for (const preset of value.promptPresets) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "demo-button demo-button--secondary";
      button.dataset.presetId = preset.id;
      button.textContent = preset.label;
      button.addEventListener("click", () => {
        if (phase !== "idle") return;
        systemPrompt.value = preset.instructions;
        updatePromptSelection();
      });
      promptPresets.append(button);
    }
    updatePromptSelection();
    modelName.textContent = value.model;
    document.querySelector("#durationHint").textContent =
      `${value.minSessionSeconds / 60}-${value.maxSessionSeconds / 60} minutes, one minute at a time. Locked during a conversation.`;
    if (value.user) {
      document.querySelector("#readerName").textContent = value.user;
      document.querySelector("#readerName").hidden = false;
      document.querySelector("#logoutLink").hidden = false;
    }
    setPhase("idle");
    setStatus("Ready. Start a conversation when you are ready.");
  })
  .catch((error) => {
    config = null;
    setPhase("idle");
    promptSelection.textContent = "Prompt presets could not load. Reload the page to try again.";
    setStatus(
      error.name === "TimeoutError"
        ? "Configuration request timed out. Reload the page to try again."
        : error.message,
      "error",
    );
  });
