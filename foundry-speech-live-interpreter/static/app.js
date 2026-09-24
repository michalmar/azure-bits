const targetLanguage = document.querySelector("#targetLanguage");
const sessionButton = document.querySelector("#sessionButton");
const clearButton = document.querySelector("#clearButton");
const statusLine = document.querySelector("#status");
const tape = document.querySelector("#tape");
const emptyState = document.querySelector("#emptyState");
const utterances = document.querySelector("#utterances");
const interim = document.querySelector("#interim");
const interimSource = document.querySelector("#interimSource");
const interimTranslation = document.querySelector("#interimTranslation");
const audioResult = document.querySelector("#audioResult");
const audioPlayer = document.querySelector("#audioPlayer");
const downloadLink = document.querySelector("#downloadLink");
const personalVoiceChoice = document.querySelector("#personalVoiceChoice");
const userName = document.querySelector("#userName");

let socket;
let captureContext;
let playbackContext;
let sourceNode;
let processorNode;
let microphoneStream;
let listening = false;
let audioUrl;
let nextPlaybackTime = 0;
let playbackGeneration = 0;
let playbackQueue = Promise.resolve();
const playbackSources = new Set();

function setStatus(message, state = "") {
  statusLine.textContent = message;
  statusLine.dataset.state = state;
}

function selectedVoice() {
  const mode = document.querySelector('input[name="voiceMode"]:checked').value;
  return mode === "personal-voice" ? "personal-voice" : "";
}

function resampleTo16k(input, inputRate) {
  if (inputRate === 16000) return input;
  const ratio = inputRate / 16000;
  const output = new Float32Array(Math.round(input.length / ratio));
  for (let index = 0; index < output.length; index += 1) {
    const start = Math.floor(index * ratio);
    const end = Math.min(Math.floor((index + 1) * ratio), input.length);
    let sum = 0;
    for (let sourceIndex = start; sourceIndex < end; sourceIndex += 1) sum += input[sourceIndex];
    output[index] = sum / Math.max(1, end - start);
  }
  return output;
}

function floatToPcm16(values) {
  const buffer = new ArrayBuffer(values.length * 2);
  const view = new DataView(buffer);
  values.forEach((value, index) => {
    const clamped = Math.max(-1, Math.min(1, value));
    view.setInt16(index * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  });
  return buffer;
}

function base64Bytes(value) {
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
}

function scheduleAudioBuffer(audioBuffer, generation) {
  if (
    generation !== playbackGeneration ||
    !playbackContext ||
    playbackContext.state === "closed"
  ) {
    return;
  }
  const source = playbackContext.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(playbackContext.destination);
  const startTime = Math.max(playbackContext.currentTime + 0.03, nextPlaybackTime);
  source.start(startTime);
  nextPlaybackTime = startTime + audioBuffer.duration;
  playbackSources.add(source);
  source.addEventListener("ended", () => playbackSources.delete(source), { once: true });
}

function pcm16AudioBuffer(bytes) {
  if (!playbackContext || bytes.byteLength < 2) return null;
  const sampleCount = Math.floor(bytes.byteLength / 2);
  const pcm = new DataView(bytes.buffer, bytes.byteOffset, sampleCount * 2);
  const audioBuffer = playbackContext.createBuffer(1, sampleCount, 16000);
  const channel = audioBuffer.getChannelData(0);
  for (let index = 0; index < sampleCount; index += 1) {
    channel[index] = pcm.getInt16(index * 2, true) / 0x8000;
  }
  return audioBuffer;
}

async function playAudioChunk(bytes, format, generation) {
  if (!playbackContext || playbackContext.state === "closed") return;
  const audioBuffer =
    format === "wav"
      ? await playbackContext.decodeAudioData(
          bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
        )
      : pcm16AudioBuffer(bytes);
  if (audioBuffer) scheduleAudioBuffer(audioBuffer, generation);
}

function stopPlayback() {
  playbackGeneration += 1;
  playbackSources.forEach((source) => {
    try {
      source.stop();
    } catch (error) {
      if (error.name !== "InvalidStateError") throw error;
    }
  });
  playbackSources.clear();
  nextPlaybackTime = playbackContext?.currentTime || 0;
  playbackQueue = Promise.resolve();
}

function translationText(translations) {
  return Object.values(translations || {}).join(" ");
}

function addUtterance(source, translated) {
  if (!source && !translated) return;
  emptyState.hidden = true;
  const row = document.createElement("div");
  row.className = "utterance";
  const sourceText = document.createElement("p");
  sourceText.className = "utterance__source";
  sourceText.textContent = source || "No source text returned.";
  const translation = document.createElement("p");
  translation.className = "utterance__translation";
  translation.textContent = translated || "No translation returned.";
  row.append(sourceText, translation);
  utterances.append(row);
  clearButton.disabled = false;
}

function handleMessage(event) {
  const message = JSON.parse(event.data);
  if (message.type === "ready") {
    setStatus(`Listening with ${message.voice}.`, "active");
  } else if (message.type === "recognizing") {
    interim.hidden = false;
    interimSource.textContent = message.source;
    interimTranslation.textContent = translationText(message.translations);
  } else if (message.type === "recognized") {
    interim.hidden = true;
    addUtterance(message.source, translationText(message.translations));
  } else if (message.type === "audio_chunk") {
    const generation = playbackGeneration;
    const bytes = base64Bytes(message.data);
    playbackQueue = playbackQueue
      .then(() => playAudioChunk(bytes, message.format, generation))
      .catch((error) => {
        setStatus(`Translated audio could not play: ${error.message}`, "error");
      });
    setStatus("Playing translated speech…", "active");
  } else if (message.type === "audio") {
    const bytes = base64Bytes(message.data);
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    audioUrl = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
    audioPlayer.src = audioUrl;
    downloadLink.href = audioUrl;
    audioResult.hidden = false;
  } else if (message.type === "error") {
    setStatus(message.message, "error");
    stopCapture(false);
    socket.close();
  } else if (message.type === "stopped") {
    setStatus("Session complete. Start again to continue.");
  }
}

async function startCapture() {
  setStatus("Requesting microphone access…");
  if (!playbackContext || playbackContext.state === "closed") {
    playbackContext = new AudioContext();
  }
  await playbackContext.resume();
  stopPlayback();
  microphoneStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${location.host}/api/interpret`);
  socket.addEventListener("message", handleMessage);
  socket.addEventListener("close", () => {
    if (listening) stopCapture(false);
  });
  socket.addEventListener("error", () => setStatus("The interpreter connection failed.", "error"));
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  socket.send(JSON.stringify({ targetLanguage: targetLanguage.value, voice: selectedVoice() }));

  captureContext = new AudioContext();
  sourceNode = captureContext.createMediaStreamSource(microphoneStream);
  processorNode = captureContext.createScriptProcessor(4096, 1, 1);
  processorNode.onaudioprocess = (audioEvent) => {
    if (socket.readyState !== WebSocket.OPEN) return;
    const input = audioEvent.inputBuffer.getChannelData(0);
    socket.send(floatToPcm16(resampleTo16k(input, captureContext.sampleRate)));
  };
  sourceNode.connect(processorNode);
  processorNode.connect(captureContext.destination);
  listening = true;
  tape.classList.add("is-live");
  sessionButton.textContent = "Stop interpreting";
  sessionButton.classList.add("is-listening");
  targetLanguage.disabled = true;
  document.querySelectorAll('input[name="voiceMode"]').forEach((input) => {
    input.disabled = true;
  });
}

async function stopCapture(sendStop = true) {
  listening = false;
  tape.classList.remove("is-live");
  sessionButton.textContent = "Start interpreting";
  sessionButton.classList.remove("is-listening");
  targetLanguage.disabled = false;
  document.querySelectorAll('input[name="voiceMode"]').forEach((input) => {
    input.disabled = false;
  });
  if (processorNode) processorNode.disconnect();
  if (sourceNode) sourceNode.disconnect();
  if (microphoneStream) microphoneStream.getTracks().forEach((track) => track.stop());
  if (captureContext) await captureContext.close();
  processorNode = null;
  sourceNode = null;
  microphoneStream = null;
  captureContext = null;
  if (sendStop && socket?.readyState === WebSocket.OPEN) {
    setStatus("Finishing translated audio…");
    socket.send("stop");
  }
}

document.querySelector("#controls").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (listening) {
    await stopCapture();
    return;
  }
  try {
    await startCapture();
  } catch (error) {
    await stopCapture(false);
    setStatus(`Microphone could not start: ${error.message}`, "error");
  }
});

clearButton.addEventListener("click", () => {
  stopPlayback();
  utterances.replaceChildren();
  interim.hidden = true;
  emptyState.hidden = false;
  audioResult.hidden = true;
  audioPlayer.removeAttribute("src");
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  audioUrl = null;
  clearButton.disabled = true;
  setStatus("Conversation cleared.");
});

fetch("/api/config")
  .then((response) => {
    if (!response.ok) throw new Error(`Configuration request failed (${response.status}).`);
    return response.json();
  })
  .then((config) => {
    personalVoiceChoice.hidden = !config.personalVoiceAvailable;
    if (config.user?.name) {
      userName.textContent = config.user.name;
      userName.hidden = false;
    }
  })
  .catch((error) => setStatus(error.message, "error"));
