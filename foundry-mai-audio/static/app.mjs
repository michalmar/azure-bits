import { models, estimatedCost, updateTranscript } from "./format.mjs";
const $ = (id) => document.getElementById(id);
let config, samples = [], selectedText = "", recording = null;
const resultUrls = new Set();
const message = (id, text, error = false) => { $(id).textContent = text; $(id).classList.toggle("error", error); };

function view(name) {
  if (recording && name !== "playground") stopRecording();
  for (const id of ["listen", "playground"]) $(id).hidden = id !== name;
  document.querySelectorAll("[data-view]").forEach((button) => {
    const active = button.dataset.view === name;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
}
document.querySelectorAll("[data-view]").forEach((button) => button.onclick = () => view(button.dataset.view));
function mode(captions) {
  if (recording && !captions) stopRecording();
  $("caption-workbench").hidden = !captions;
  $("voice-workbench").hidden = captions;
  $("voice-mode").setAttribute("aria-pressed", String(!captions));
  $("caption-mode").setAttribute("aria-pressed", String(captions));
}
$("voice-mode").onclick = () => mode(false);
$("caption-mode").onclick = () => mode(true);

function audioOutput(model, url, note) {
  const section = document.createElement("article");
  section.className = "audio-output";
  const heading = document.createElement("h3");
  heading.textContent = model;
  const audio = document.createElement("audio");
  audio.controls = true;
  audio.preload = "none";
  audio.src = url;
  audio.setAttribute("aria-label", `${model} audio`);
  audio.onplay = () => document.querySelectorAll("audio").forEach(other => { if (other !== audio) other.pause(); });
  audio.onerror = () => { detail.textContent = "Audio could not be loaded. Sign in again or reload the page."; detail.classList.add("error"); };
  const detail = document.createElement("p");
  detail.textContent = note;
  const download = document.createElement("a");
  download.href = url;
  download.download = `${model}.mp3`;
  download.textContent = "Download audio";
  section.append(heading, audio, detail, download);
  return section;
}

function gallery() {
  const rows = samples.filter(value => value.scenario === $("scenario").value);
  $("gallery").replaceChildren();
  selectedText = rows[0]?.text || "";
  $("sample-text").textContent = selectedText;
  $("try-example").disabled = !rows.length;
  if (!rows.length) {
    message("gallery-status", "No cached clip for this example yet. A publisher must generate the MAI gallery; the live playground is separate.");
    return;
  }
  message("gallery-status", "Cached MAI audio · No inference on replay");
  for (const row of rows) {
    $("gallery").append(audioOutput(row.model, row.path, `${row.voice} · ${row.style} · Recorded generation ${row.generation_ms} ms (complete audio)`));
  }
}
$("scenario").onchange = gallery;
$("try-example").onclick = () => {
  const sample = samples.find(value => value.scenario === $("scenario").value);
  if (!sample) return;
  $("text").value = selectedText;
  $("voice").value = sample.voice;
  styles();
  $("style").value = sample.style;
  estimate();
  mode(false);
  view("playground");
};
function styles() {
  $("style").replaceChildren();
  for (const style of config.voices.find(v => v.id === $("voice").value).styles) {
    const option = document.createElement("option");
    option.value = style;
    option.textContent = style.replaceAll("_", " ");
    $("style").append(option);
  }
}
function estimate() {
  const text = $("text").value;
  $("estimate").textContent = `${Array.from(text).length} / 600 characters · Launch-price estimate: Voice $${estimatedCost(text, models[0]).toFixed(4)} · Flash $${estimatedCost(text, models[1]).toFixed(4)}. Not metered billing.`;
}
$("voice").onchange = () => styles();
$("text").oninput = estimate;
$("speech-form").onsubmit = async (event) => {
  event.preventDefault();
  $("generate").disabled = true;
  $("generate").textContent = "Generating...";
  for (const url of resultUrls) URL.revokeObjectURL(url);
  resultUrls.clear();
  $("results").replaceChildren();
  message("generation-status", "Requesting MAI audio. Your text is preserved.");
  const text = $("text").value, voice = $("voice").value, style = $("style").value;
  const selected = $("model").value === "both" ? models : [$("model").value];
  const started = performance.now();
  const results = await Promise.allSettled(selected.map(async model => {
    const response = await fetch("/api/synthesize", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({model, voice, style, text}),
      signal: AbortSignal.timeout(90000),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(`${model}: ${error.detail || `HTTP ${response.status}`}`);
    }
    const server = response.headers.get("X-Generation-Ms");
    const url = URL.createObjectURL(await response.blob());
    resultUrls.add(url);
    return audioOutput(model, url, `Azure request-to-complete ${server} ms · ${voice} · ${style}`);
  }));
  for (const result of results) if (result.status === "fulfilled") $("results").append(result.value);
  const errors = results.filter(result => result.status === "rejected").map(result => result.reason.message);
  message("generation-status", errors.length ? errors.join(" ") : `Audio ready. Browser round trip: ${Math.round(performance.now() - started)} ms.`, errors.length > 0);
  $("generate").textContent = "Generate speech";
  $("generate").disabled = !config.live_enabled;
};

async function cleanup(record) {
  if (record.timer) clearTimeout(record.timer);
  record.stream?.getTracks().forEach(track => track.stop());
  record.node?.disconnect();
  record.source?.disconnect();
  if (record.context && record.context.state !== "closed") await record.context.close();
}
function stopRecording() {
  const record = recording;
  if (!record || record.stopping) return;
  record.stopping = true;
  $("stop").disabled = true;
  message("record-status", "Finalizing the last segment...");
  if (record.node) record.node.port.postMessage("stop");
  else {
    record.socket?.close();
    cleanup(record);
    message("record-status", "Recording cancelled before audio capture.");
    return;
  }
  record.drain = setTimeout(() => {
    message("record-status", "Finalization timed out. The available transcript is preserved.", true);
    record.socket.close();
  }, 50000);
}
async function startupCancelled(record) {
  if (!record.stopping) return false;
  await cleanup(record);
  if (recording === record) recording = null;
  $("record").disabled = !config.live_enabled;
  $("stop").disabled = true;
  return true;
}
$("stop").onclick = stopRecording;
$("record").onclick = async () => {
  if (recording) return;
  $("record").disabled = true;
  $("transcript-download").hidden = true;
  $("final-text").textContent = "";
  $("partial-text").textContent = "";
  message("caption-metrics", "Waiting for the first caption...");
  message("record-status", "Allow microphone access. No audio is sent until MAI is ready.");
  const record = {stopping: false, items: new Map(), firstText: null, ready: false};
  recording = record;
  try {
    record.stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true}});
    if (await startupCancelled(record)) return;
    record.context = new AudioContext();
    await record.context.audioWorklet.addModule("/pcm-worklet.js");
    if (await startupCancelled(record)) return;
    await record.context.resume();
    if (await startupCancelled(record)) return;
    record.socket = new WebSocket(`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/transcribe`);
    record.socket.binaryType = "arraybuffer";
    record.timer = setTimeout(() => { message("record-status", "MAI connection timed out. Retry recording.", true); record.socket.close(); }, 45000);
    record.socket.onmessage = async ({data}) => {
      const event = JSON.parse(data);
      if (event.type === "ready") {
        if (record.stopping) { record.socket.close(); await cleanup(record); return; }
        clearTimeout(record.timer);
        record.ready = true;
        record.source = record.context.createMediaStreamSource(record.stream);
        record.node = new AudioWorkletNode(record.context, "pcm-recorder");
        record.node.port.onmessage = ({data}) => {
          if (data === "stopped") {
            if (record.socket.readyState === WebSocket.OPEN) record.socket.send("stop");
            cleanup(record);
          } else if (record.socket.readyState === WebSocket.OPEN) {
            if (record.socket.bufferedAmount > 32000) {
              message("record-status", "Network cannot keep up with live audio. Recording stopped; retry on a faster connection.", true);
              record.socket.close();
              cleanup(record);
            } else record.socket.send(data);
          }
        };
        record.source.connect(record.node);
        // Worklet output is silence; destination keeps audio processing scheduled.
        record.node.connect(record.context.destination);
        $("stop").disabled = false;
        message("record-status", "Microphone is live · Automatic language detection · 60 seconds maximum");
        record.timer = setTimeout(stopRecording, 59500);
      } else if (event.type.startsWith("conversation.item.input_audio_transcription.")) {
        updateTranscript(record.items, event);
        $("final-text").textContent = [...record.items.values()].map(item => item.stable).join("\n");
        $("partial-text").textContent = [...record.items.values()].filter(item => !item.final).map(item => item.partial).join("\n");
        if (event.first_text_ms != null) {
          record.firstText = event.first_text_ms;
          message("caption-metrics", `First text ${record.firstText} ms after the first audio chunk reached the backend. Not per-word latency.`);
        }
      } else if (event.type === "done") {
        message("record-status", `Microphone off. Final transcript ready (${event.audio_seconds.toFixed(1)} seconds of audio).`);
        const url = URL.createObjectURL(new Blob([$("final-text").textContent], {type: "text/plain"}));
        if ($("transcript-download").dataset.url) URL.revokeObjectURL($("transcript-download").dataset.url);
        $("transcript-download").href = url;
        $("transcript-download").dataset.url = url;
        $("transcript-download").download = "mai-transcript.txt";
        $("transcript-download").hidden = false;
        record.done = true;
        record.socket.close();
      } else if (event.type === "error") {
        message("record-status", event.message, true);
        record.failed = true;
        record.socket.close();
      }
    };
    record.socket.onerror = () => {
      record.failed = true;
      message("record-status", "Streaming connection failed. Sign in again or check model availability, then retry.", true);
    };
    record.socket.onclose = async () => {
      clearTimeout(record.drain);
      await cleanup(record);
      if (!record.done && !record.failed && !$("record-status").classList.contains("error")) message("record-status", "Connection closed before finalization. Available captions are preserved; retry recording.", true);
      if (recording === record) recording = null;
      $("record").disabled = !config.live_enabled;
      $("stop").disabled = true;
    };
  } catch (error) {
    await cleanup(record);
    recording = null;
    $("record").disabled = !config.live_enabled;
    if (record.stopping) return;
    message("record-status", `Microphone could not start: ${error.message}. Check permission and use HTTPS or localhost.`, true);
  }
};
$("logout").onclick = async () => {
  if (recording) stopRecording();
  const response = await fetch("/logout", {method: "POST"});
  if (response.ok) location.assign("/login");
  else message("live-status", "Sign-out failed. Reload and try again.", true);
};
window.addEventListener("pagehide", () => {
  if (recording) { recording.socket?.close(); cleanup(recording); }
  for (const url of resultUrls) URL.revokeObjectURL(url);
});
async function initialize() {
  estimate();
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error(`Configuration returned HTTP ${response.status}. Sign in and reload.`);
    config = await response.json();
    for (const voice of config.voices) {
      const option = document.createElement("option");
      option.value = voice.id;
      option.textContent = `${voice.id} · ${voice.language}`;
      $("voice").append(option);
    }
    styles();
    $("generate").disabled = !config.live_enabled;
    $("record").disabled = !config.live_enabled || !navigator.mediaDevices?.getUserMedia;
    $("logout").hidden = !config.authenticated;
    message("live-status", config.live_enabled ? "Live MAI calls enabled · Azure managed identity · Short requests only" : "Static mode. Live calls need an Azure managed-identity host; no credential fallback is used.");
  } catch (error) { message("live-status", error.message, true); }
  try {
    const response = await fetch("/samples.json");
    if (!response.ok) throw new Error(`Gallery returned HTTP ${response.status}`);
    samples = (await response.json()).samples;
    gallery();
  } catch (error) { message("gallery-status", `${error.message}. Reload after the publisher uploads cached audio.`, true); }
}
initialize();
