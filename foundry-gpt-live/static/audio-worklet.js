class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.muted = false;
    this.position = 0;
    this.nextOutput = 0;
    this.previous = 0;
    this.samples = [];
    this.levelSamples = 0;
    this.levelSum = 0;
    this.port.onmessage = ({ data }) => {
      if (data?.type === "mute" && typeof data.muted === "boolean") {
        this.muted = data.muted;
        this.samples = [];
        this.nextOutput = this.position;
      }
    };
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    const ratio = sampleRate / 24000;
    for (const current of channel) {
      this.levelSum += current * current;
      this.levelSamples += 1;
      if (this.position === 0) this.previous = current;
      if (!this.muted) {
        while (this.nextOutput <= this.position) {
          const fraction = Math.max(0, Math.min(1, this.nextOutput - this.position + 1));
          this.samples.push(this.previous + (current - this.previous) * fraction);
          this.nextOutput += ratio;
        }
        if (this.samples.length >= 480) {
          const bytes = new ArrayBuffer(this.samples.length * 2);
          const view = new DataView(bytes);
          this.samples.forEach((value, index) => {
            const clamped = Math.max(-1, Math.min(1, value));
            view.setInt16(
              index * 2,
              clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff,
              true,
            );
          });
          this.port.postMessage({ type: "audio", buffer: bytes }, [bytes]);
          this.samples = [];
        }
      }
      this.previous = current;
      this.position += 1;
    }
    if (this.levelSamples >= sampleRate / 10) {
      this.port.postMessage({
        type: "level",
        value: this.muted ? 0 : Math.min(1, Math.sqrt(this.levelSum / this.levelSamples) * 5),
      });
      this.levelSamples = 0;
      this.levelSum = 0;
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCapture);
