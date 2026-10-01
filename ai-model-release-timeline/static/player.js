import { createTimeline } from "./timeline.js";

const canvas = document.querySelector("#stage");
const playButton = document.querySelector("#play-button");
const restartButton = document.querySelector("#restart-button");
const scrubber = document.querySelector("#scrubber");
const readout = document.querySelector("#time-readout");
const status = document.querySelector("#player-status");
const error = document.querySelector("#player-error");

let timeline;
let currentTime = 0;
let startedAt = 0;
let frameRequest = 0;
let playing = false;

function formatTime(seconds) {
  const whole = Math.max(0, Math.round(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function render() {
  timeline.render(currentTime);
  scrubber.value = String(currentTime);
  readout.value = `${formatTime(currentTime)} / ${formatTime(timeline.duration)}`;
}

function setPlaying(nextPlaying) {
  playing = nextPlaying;
  playButton.textContent = playing ? "Pause" : "Play";
  playButton.setAttribute("aria-pressed", String(playing));

  if (!playing) {
    cancelAnimationFrame(frameRequest);
    return;
  }

  if (currentTime >= timeline.duration) currentTime = 0;
  startedAt = performance.now() - currentTime * 1000;
  frameRequest = requestAnimationFrame(tick);
}

function tick(now) {
  currentTime = Math.min((now - startedAt) / 1000, timeline.duration);
  render();
  if (currentTime >= timeline.duration) {
    setPlaying(false);
    return;
  }
  frameRequest = requestAnimationFrame(tick);
}

playButton.addEventListener("click", () => setPlaying(!playing));

restartButton.addEventListener("click", () => {
  currentTime = 0;
  render();
  if (playing) startedAt = performance.now();
});

scrubber.addEventListener("input", () => {
  currentTime = Number(scrubber.value);
  render();
  if (playing) startedAt = performance.now() - currentTime * 1000;
});

try {
  const response = await fetch("./releases.json");
  if (!response.ok) throw new Error(`Release data request failed (${response.status})`);
  timeline = createTimeline(canvas, await response.json());
  scrubber.max = String(timeline.duration);
  playButton.disabled = false;
  restartButton.disabled = false;
  scrubber.disabled = false;
  status.textContent = `${timeline.releases.length} releases · ${timeline.sameDay.length} same-day launches · ${formatTime(timeline.duration)} runtime`;
  render();
} catch (loadError) {
  console.error(loadError);
  status.textContent = "Release data could not be loaded.";
  canvas.hidden = true;
  error.hidden = false;
}
