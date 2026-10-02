import assert from "node:assert/strict";
import test from "node:test";

test("changing views cancels pending microphone, worklet and context startup", async (t) => {
  for (const stage of ["permission", "worklet", "resume"]) {
    await t.test(stage, async () => {
      const names = ["document", "window", "navigator", "fetch", "AudioContext", "WebSocket"];
      const previous = new Map(names.map(name => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
      const elements = new Map();
      const element = id => {
        if (!elements.has(id)) elements.set(id, {
          value: id === "voice" ? "en-US-Harper" : "",
          disabled: false, dataset: {}, classList: {toggle() {}, contains() { return false; }},
          replaceChildren() {}, append() {}, setAttribute() {}, removeAttribute() {},
        });
        return elements.get(id);
      };
      const tab = {...element("listen-tab"), dataset: {view: "listen"}};
      let release, stopped = 0, sockets = 0;
      const pending = new Promise(resolve => { release = resolve; });
      const stream = {getTracks: () => [{stop: () => stopped++}]};
      class Context {
        state = "running";
        audioWorklet = {addModule: () => stage === "worklet" ? pending : Promise.resolve()};
        resume() { return stage === "resume" ? pending : Promise.resolve(); }
        async close() { this.state = "closed"; }
      }
      const globals = {
        document: {
          getElementById: element, querySelectorAll: () => [tab],
          createElement: () => element("new-option"),
        },
        window: {addEventListener() {}},
        navigator: {mediaDevices: {
          getUserMedia: () => stage === "permission" ? pending : Promise.resolve(stream),
        }},
        fetch: async url => ({ok: true, json: async () => url === "/api/config"
          ? {live_enabled: true, voices: [{id: "en-US-Harper", styles: ["neutral"]}]}
          : {samples: []}}),
        AudioContext: Context,
        WebSocket: class { constructor() { sockets++; throw new Error("Cancelled startup opened a socket"); } },
      };
      try {
        for (const [name, value] of Object.entries(globals)) {
          Object.defineProperty(globalThis, name, {configurable: true, writable: true, value});
        }
        await import(`../static/app.mjs?cancel=${stage}`);
        await new Promise(resolve => setImmediate(resolve));
        const starting = element("record").onclick();
        await new Promise(resolve => setImmediate(resolve));
        assert.doesNotThrow(() => tab.onclick());
        release(stage === "permission" ? stream : undefined);
        await starting;
        assert.ok(stopped > 0, "microphone tracks are stopped");
        assert.equal(sockets, 0);
        assert.equal(element("record").disabled, false, "recording can be retried");
        assert.equal(element("stop").disabled, true);
      } finally {
        for (const name of names) {
          const descriptor = previous.get(name);
          if (descriptor) Object.defineProperty(globalThis, name, descriptor);
          else delete globalThis[name];
        }
      }
    });
  }
});
