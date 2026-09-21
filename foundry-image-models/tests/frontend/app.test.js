const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const app = require(path.join(__dirname, "../../static/app.js"));

test("buildGenerateRequest uses multipart form data and default settings only", () => {
  const file = new File(["demo"], "reference.png", { type: "image/png" });
  const { url, init } = app.buildGenerateRequest({
    model: { key: "MAI-Image-2.6", displayName: "MAI-Image-2.6" },
    prompt: "A calibrated proof bench",
    imageFile: file,
  });

  assert.equal(url, "/api/generate");
  assert.equal(init.method, "POST");
  assert.ok(init.body instanceof FormData);
  assert.equal(init.body.get("model"), "MAI-Image-2.6");
  assert.equal(init.body.get("prompt"), "A calibrated proof bench");
  assert.equal(init.body.get("image").name, "reference.png");
  assert.equal(init.body.has("settings"), false);
});

test("resetSessionState clears browser-session data and revokes object URLs", () => {
  const state = app.createSessionState();
  state.playground.uploadPreviewUrl = "blob:preview";
  state.playground.results = [
    { id: "1", objectUrl: "blob:one" },
    { id: "2", objectUrl: "blob:two" },
  ];
  state.playground.prompt = "prompt";
  state.playground.uploadFile = new File(["demo"], "reference.png", { type: "image/png" });
  state.playground.latestResultId = "2";

  const revoked = [];
  app.resetSessionState(state, {
    revokeObjectURL: (url) => revoked.push(url),
  });

  assert.deepEqual(revoked, ["blob:preview", "blob:one", "blob:two"]);
  assert.equal(state.playground.prompt, "");
  assert.equal(state.playground.uploadFile, null);
  assert.equal(state.playground.uploadPreviewUrl, "");
  assert.equal(state.playground.results.length, 0);
  assert.equal(state.playground.latestResultId, "");
  assert.equal(state.gallery.promptIndex, 0);
  assert.equal(state.gallery.inspection.x, 0.5);
  assert.equal(state.gallery.inspection.y, 0.5);
});

test("parseSessionPayload returns a signed-in user only for authenticated responses", () => {
  const signedIn = app.parseSessionPayload({
    authenticated: true,
    user: { name: "Ada Lovelace", username: "ada" },
  });
  const signedOut = app.parseSessionPayload({ authenticated: false, user: { name: "X", username: "x" } });
  const anonymous = app.parseSessionPayload(null);

  assert.deepEqual(signedIn, {
    authenticated: true,
    user: { name: "Ada Lovelace", username: "ada" },
  });
  assert.deepEqual(signedOut, { authenticated: false, user: null });
  assert.deepEqual(anonymous, { authenticated: false, user: null });
});

test("parseCapability treats unsupported values as unsupported", () => {
  assert.deepEqual(app.parseCapability({ imageInput: { status: "unsupported" } }), {
    status: "unsupported",
    label: "Unsupported",
    note: "Image input is not available.",
  });
  assert.deepEqual(app.parseCapability({ imageInput: "disabled" }), {
    status: "unsupported",
    label: "Unsupported",
    note: "Image input is not available.",
  });
});

test("parseCapability reads nested imageEdits capability payloads", () => {
  assert.deepEqual(
    app.parseCapability({ capabilities: { imageEdits: { status: "ready", value: true } } }),
    { status: "supported", label: "Supported", note: "Image input is available." }
  );
  assert.equal(
    app.parseCapability({ capabilities: { imageEdits: { status: "unsupported", value: false } } }).status,
    "unsupported"
  );
});

test("frontend code does not reference persistent browser storage APIs", () => {
  const source = fs.readFileSync(path.join(__dirname, "../../static/app.js"), "utf8");
  const forbidden = ["localStorage", "sessionStorage", "indexedDB", "serviceWorker", "document.cookie", "cookie"];
  for (const token of forbidden) {
    assert.equal(
      source.includes(token),
      false,
      `Expected app.js to avoid persistence API token: ${token}`
    );
  }
});

test("upload control is keyboard-triggered and not hidden", () => {
  const html = fs.readFileSync(path.join(__dirname, "../../static/index.html"), "utf8");
  const imageInputBlock = html.match(/<input[\s\S]*?id="imageInput"[\s\S]*?>/);

  assert.match(imageInputBlock?.[0] || "", /id="imageInput"/);
  assert.match(imageInputBlock?.[0] || "", /type="file"/);
  assert.match(imageInputBlock?.[0] || "", /tabindex="-1"/);
  assert.doesNotMatch(imageInputBlock?.[0] || "", /hidden/);
  assert.match(html, /id="chooseImageButton"/);
});

test("comparison rail keeps visible focus and the minimal design avoids plate lift", () => {
  const css = fs.readFileSync(path.join(__dirname, "../../static/styles.css"), "utf8");
  const tokens = fs.readFileSync(path.join(__dirname, "../../static/tokens.css"), "utf8");

  assert.match(css, /\.comparison-rail:focus-visible/);
  assert.doesNotMatch(css, /\.proof-plate:hover[\s\S]{0,120}translateY/);
  assert.match(tokens, /\.proof-plate:hover\s*\{\s*transform:\s*none\s*!important;/s);
});

test("createApp boot wires session, gallery, upload, and reset controls", async () => {
  const dom = createStubDom();
  const appInstance = app.createApp(dom.document, createFetchStub());

  await appInstance.boot();

  assert.equal(dom.elements.sessionChip.hidden, false);
  assert.equal(dom.elements.sessionName.textContent, "AL");
  assert.equal(dom.elements.sessionUsername.textContent, "@ada");
  assert.match(dom.elements.galleryPromptLead.textContent, /ceramic lamp/);
  assert.equal(dom.elements.chooseImageButton.disabled, false);

  dom.promptTabs[1].click();
  assert.match(dom.elements.galleryPromptLead.textContent, /rain-wet tram stop/);

  let pickerClicks = 0;
  dom.elements.imageInput.click = () => {
    pickerClicks += 1;
  };
  dom.elements.chooseImageButton.click();
  assert.equal(pickerClicks, 1);

  dom.elements.promptInput.value = "Build a paper lantern";
  dom.elements.promptInput.dispatchEvent({ type: "input", target: dom.elements.promptInput });
  assert.equal(dom.elements.generateButton.disabled, false);

  appInstance.state.playground.uploadFile = new File(["demo"], "reference.png", { type: "image/png" });
  appInstance.state.playground.uploadPreviewUrl = "blob:preview";
  appInstance.state.playground.uploadPreviewName = "reference.png";
  appInstance.state.playground.results = [
    {
      id: "1",
      objectUrl: "blob:one",
      modelName: "MAI-Image-2.6",
      caption: "Caption",
      src: "data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1' height='1'/%3E",
      alt: "Alt",
      prompt: "Prompt",
      metadata: [],
    },
  ];
  appInstance.state.playground.latestResultId = "1";
  dom.elements.uploadPreview.hidden = false;
  dom.elements.uploadPreviewFrame.innerHTML =
    "<img src='data:image/svg+xml;utf8,%3Csvg xmlns=\"http://www.w3.org/2000/svg\" width=\"1\" height=\"1\"/%3E' alt='preview' />";
  appInstance.render();

  dom.elements.modelSelect.value = "MAI-Image-2.6-Flash";
  dom.elements.modelSelect.dispatchEvent({ type: "change", target: dom.elements.modelSelect });
  assert.equal(dom.elements.chooseImageButton.disabled, true);
  assert.equal(dom.elements.imageInput.disabled, true);

  const blockedFile = new File(["blocked"], "blocked.png", { type: "image/png" });
  dom.elements.uploadDropzone.dispatchEvent({
    type: "dragover",
    target: dom.elements.uploadDropzone,
    preventDefault() {
      this.prevented = true;
    },
  });
  dom.elements.uploadDropzone.dispatchEvent({
    type: "drop",
    target: dom.elements.uploadDropzone,
    dataTransfer: { files: [blockedFile] },
    preventDefault() {
      this.prevented = true;
    },
  });
  assert.equal(appInstance.state.playground.uploadFile, null);
  assert.equal(appInstance.state.playground.uploadPreviewUrl, "");
  assert.equal(dom.elements.uploadPreview.hidden, true);

  dom.elements.resetButton.click();

  assert.equal(appInstance.state.playground.prompt, "");
  assert.equal(appInstance.state.playground.uploadFile, null);
  assert.equal(appInstance.state.playground.results.length, 0);
  assert.equal(dom.elements.promptInput.value, "");
  assert.equal(dom.elements.uploadPreview.hidden, true);
  assert.match(dom.elements.resultHistory.innerHTML, /Generated results will appear here/);
  assert.equal(appInstance.state.session.authenticated, true);
});

function createFetchStub() {
  const galleryPayload = {
    prompts: [
      createPromptGroup(
        "prompt-1",
        "Prompt 1",
        "A studio portrait of a ceramic lamp on a proof bench, lit by one soft window.",
      ),
      createPromptGroup(
        "prompt-2",
        "Prompt 2",
        "A rain-wet tram stop at dusk with reflective pavement and bright signage.",
      ),
      createPromptGroup(
        "prompt-3",
        "Prompt 3",
        "A precise tabletop still life of citrus, glassware, and a steel knife.",
      ),
    ],
  };

  const modelsPayload = [
    "gpt-image-2.5-sunburst",
    "MAI-Image-2.6-Flash",
    "MAI-Image-2.6",
    "MAI-Image-2.5",
    "gpt-image-2",
  ].map((deploymentName, index) => ({
    id: deploymentName,
    displayName: deploymentName,
    deploymentName,
    imageInput: index === 1 ? { status: "unsupported" } : { status: "supported" },
    description: `Model ${index + 1}`,
  }));

  return async function fetchStub(url) {
    if (url === "/api/gallery") {
      return createResponse(galleryPayload);
    }
    if (url === "/api/models") {
      return createResponse(modelsPayload);
    }
    if (url === "/api/session") {
      return createResponse({
        authenticated: true,
        user: { name: "Ada Lovelace", username: "ada" },
      });
    }
    throw new Error(`Unexpected fetch URL: ${url}`);
  };
}

function createPromptGroup(id, title, prompt) {
  return {
    id,
    title,
    prompt,
    images: [
      "gpt-image-2.5-sunburst",
      "MAI-Image-2.6-Flash",
      "MAI-Image-2.6",
      "MAI-Image-2.5",
      "gpt-image-2",
    ].map((deploymentName, index) => ({
      deploymentName,
      model: deploymentName,
      alt: `${title} ${index + 1}`,
      imageUrl: `data:image/svg+xml;utf8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='8' height='8'%3E%3Crect width='8' height='8' fill='%23d8e0ea'/%3E%3C/svg%3E`,
      seed: index + 1,
    })),
  };
}

function createResponse(payload) {
  return {
    ok: true,
    status: 200,
    headers: {
      get(name) {
        return name.toLowerCase() === "content-type" ? "application/json" : null;
      },
    },
    async json() {
      return payload;
    },
    async text() {
      return JSON.stringify(payload);
    },
    async blob() {
      return new Blob([JSON.stringify(payload)], { type: "application/json" });
    },
  };
}

function createStubDom() {
  const elements = {};
  const viewTabs = [
    createStubElement("galleryView", { dataset: { view: "gallery" }, classNames: ["view-tab", "is-active"] }),
    createStubElement("playgroundView", { dataset: { view: "playground" }, classNames: ["view-tab"] }),
  ];
  const promptTabs = [
    createStubElement("promptTab1", { dataset: { promptIndex: "0" }, classNames: ["prompt-tab", "is-active"] }),
    createStubElement("promptTab2", { dataset: { promptIndex: "1" }, classNames: ["prompt-tab"] }),
    createStubElement("promptTab3", { dataset: { promptIndex: "2" }, classNames: ["prompt-tab"] }),
  ];

  const ids = [
    "sessionChip",
    "sessionName",
    "sessionUsername",
    "signOutLink",
    "gallery-panel",
    "playground-panel",
    "galleryState",
    "galleryEmpty",
    "galleryError",
    "galleryPromptLead",
    "proofGrid",
    "comparisonRail",
    "announcement",
    "modelSelect",
    "capabilityCard",
    "promptInput",
    "uploadCard",
    "uploadNote",
    "uploadDropzone",
    "uploadDropzoneText",
    "chooseImageButton",
    "imageInput",
    "uploadPreview",
    "uploadPreviewFrame",
    "clearUploadButton",
    "playgroundForm",
    "generateButton",
    "resetButton",
    "resultState",
    "resultPreview",
    "resultPreviewFrame",
    "resultPreviewCaption",
    "resultHistory",
  ];

  for (const id of ids) {
    elements[id] = createStubElement(id);
  }

  elements.sessionChip.hidden = true;
  elements["gallery-panel"].hidden = false;
  elements["playground-panel"].hidden = true;
  elements.galleryEmpty.hidden = true;
  elements.galleryError.hidden = true;
  elements.uploadPreview.hidden = true;
  elements.resultPreview.hidden = true;
  elements.imageInput.disabled = false;
  elements.generateButton.disabled = true;
  elements.resetButton.disabled = false;
  elements.proofGrid.querySelectorAll = () => [];
  elements.comparisonRail.querySelectorAll = () => [];
  elements.signOutLink.href = "/logout";

  const document = {
    readyState: "complete",
    body: createStubElement("body"),
    querySelectorAll(selector) {
      if (selector === "[data-view]") return viewTabs;
      if (selector === "[data-prompt-index]") return promptTabs;
      return [];
    },
    getElementById(id) {
      return elements[id] || null;
    },
    createElement(tagName) {
      return createStubElement(tagName);
    },
    addEventListener() {},
  };

  elements.imageInput.clickCount = 0;
  elements.imageInput.click = function () {
    this.clickCount += 1;
  };

  return {
    document,
    elements,
    viewTabs,
    promptTabs,
  };
}

function createStubElement(id, options = {}) {
  const listeners = new Map();
  const classState = new Set(options.classNames || []);
  return {
    id,
    hidden: options.hidden ?? false,
    disabled: options.disabled ?? false,
    value: options.value ?? "",
    textContent: options.textContent ?? "",
    innerHTML: options.innerHTML ?? "",
    href: options.href ?? "",
    dataset: { ...(options.dataset || {}) },
    style: {
      setProperty() {},
    },
    classList: {
      add(...names) {
        names.forEach((name) => classState.add(name));
      },
      remove(...names) {
        names.forEach((name) => classState.delete(name));
      },
      toggle(name, force) {
        if (force === undefined) {
          if (classState.has(name)) {
            classState.delete(name);
            return false;
          }
          classState.add(name);
          return true;
        }
        if (force) {
          classState.add(name);
          return true;
        }
        classState.delete(name);
        return false;
      },
      contains(name) {
        return classState.has(name);
      },
    },
    addEventListener(type, handler) {
      if (!listeners.has(type)) {
        listeners.set(type, []);
      }
      listeners.get(type).push(handler);
    },
    dispatchEvent(event) {
      const type = event.type;
      const handlers = listeners.get(type) || [];
      const synthetic = {
        preventDefault() {},
        stopPropagation() {},
        currentTarget: this,
        target: event.target || this,
        ...event,
      };
      for (const handler of handlers) {
        handler(synthetic);
      }
      return true;
    },
    click() {
      this.dispatchEvent({ type: "click" });
    },
    focus() {
      this.focused = true;
    },
    setAttribute(name, value) {
      if (name === "hidden") {
        this.hidden = true;
        return;
      }
      this[name] = String(value);
    },
    removeAttribute(name) {
      if (name === "hidden") {
        this.hidden = false;
        return;
      }
      delete this[name];
    },
    querySelectorAll() {
      return [];
    },
    closest() {
      return null;
    },
  };
}
