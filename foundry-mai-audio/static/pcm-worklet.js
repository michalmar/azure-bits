class PCMRecorder extends AudioWorkletProcessor {
  constructor() {
    super();
    this.position = 0;
    this.sum = 0;
    this.count = 0;
    this.chunk = [];
    this.active = true;
    this.port.onmessage = ({data}) => {
      if (data === "stop") {
        this.active = false;
        if (this.chunk.length) this.flush();
        this.port.postMessage("stopped");
      }
    };
  }
  flush() {
    const pcm = new Int16Array(this.chunk);
    this.port.postMessage(pcm.buffer, [pcm.buffer]);
    this.chunk = [];
  }
  process(inputs) {
    const source = inputs[0]?.[0];
    if (!source || !this.active) return true;
    // Integrate native-rate samples into 16 kHz bins; carry fractional phase across blocks.
    const ratio = sampleRate / 16000;
    for (const sample of source) {
      this.sum += sample;
      this.count++;
      this.position++;
      if (this.position >= ratio) {
        const value = Math.max(-1, Math.min(1, this.sum / this.count));
        this.chunk.push(Math.round(value * (value < 0 ? 32768 : 32767)));
        this.position -= ratio;
        this.sum = 0;
        this.count = 0;
        if (this.chunk.length === 320) this.flush();
      }
    }
    return true;
  }
}
registerProcessor("pcm-recorder", PCMRecorder);
