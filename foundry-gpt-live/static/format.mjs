export function clock(seconds) {
  const value = Math.max(0, Math.ceil(seconds));
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}

export function elapsed(milliseconds) {
  return clock(Math.floor(Math.max(0, milliseconds) / 1000));
}

export function canMergeTranscript(previous, event) {
  return Boolean(
    previous &&
    previous.speaker === event.speaker &&
    event.startMs >= previous.endMs &&
    event.startMs - previous.endMs < 900
  );
}

export function transcriptFragment(previous, event) {
  if (canMergeTranscript(previous, event)) {
    return { ...previous, text: previous.text + event.text, endMs: event.endMs };
  }
  return { ...event };
}

export function decodePcm16(base64) {
  const binary = atob(base64);
  if (!binary.length || binary.length % 2) {
    throw new Error("The model sent invalid PCM16 audio.");
  }
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  const view = new DataView(bytes.buffer);
  const samples = new Float32Array(bytes.length / 2);
  for (let index = 0; index < samples.length; index += 1) {
    samples[index] = view.getInt16(index * 2, true) / 0x8000;
  }
  return samples;
}
