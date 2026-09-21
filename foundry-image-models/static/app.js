(function (root, factory) {
  const api = factory(root);
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.FoundryImageModels = api;
})(typeof globalThis !== "undefined" ? globalThis : window, function () {
  "use strict";

  const DEFAULT_MODEL_ORDER = [
    "gpt-image-2.5-sunburst",
    "MAI-Image-2.6-Flash",
    "MAI-Image-2.6",
    "MAI-Image-2.5",
    "gpt-image-2",
  ];

  const DEFAULT_GALLERY_PROMPTS = [
    {
      id: "prompt-1",
      title: "Prompt 1",
      prompt:
        "A studio portrait of a ceramic lamp on a proof bench, lit by one soft window, with a folded calibration chart and clean shadow edges.",
    },
    {
      id: "prompt-2",
      title: "Prompt 2",
      prompt:
        "A rain-wet tram stop at dusk with reflective pavement, bright signage, and one person holding a clear umbrella in front of the scene.",
    },
    {
      id: "prompt-3",
      title: "Prompt 3",
      prompt:
        "A precise tabletop still life of citrus, glassware, and a steel knife arranged like a measured composition under daylight.",
    },
  ];

  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function toArray(value) {
    if (Array.isArray(value)) return value;
    if (value == null) return [];
    return [value];
  }

  function coerceText(value) {
    if (value == null) return "";
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    return "";
  }

  function firstText(...values) {
    for (const value of values) {
      const text = coerceText(value).trim();
      if (text) return text;
    }
    return "";
  }

  function titleCaseFallback(index) {
    return `Prompt ${index + 1}`;
  }

  function normalizeKey(value) {
    return coerceText(value).trim().toLowerCase();
  }

  function sanitizeFileName(value) {
    return coerceText(value)
      .trim()
      .replace(/[^\w.-]+/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "")
      .toLowerCase();
  }

  function pickUrl(candidate) {
    if (!candidate) return "";
    if (typeof candidate === "string") return candidate;
    if (!isObject(candidate)) return "";
    return (
      candidate.imageUrl ||
      candidate.imageURL ||
      candidate.url ||
      candidate.src ||
      candidate.href ||
      candidate.dataUrl ||
      candidate.dataURL ||
      candidate.image ||
      candidate.contentUrl ||
      ""
    );
  }

  function extractMetadataEntries(source, keys) {
    const entries = [];
    if (!isObject(source)) return entries;
    for (const key of keys) {
      if (source[key] == null) continue;
      const value = source[key];
      if (typeof value === "object") continue;
      const text = coerceText(value).trim();
      if (text) entries.push([key, text]);
    }
    return entries;
  }

  function collectRenderableMetadata(source, preferredKeys) {
    if (!isObject(source)) return [];
    const entries = extractMetadataEntries(source, preferredKeys);
    if (entries.length) return entries;
    const fallback = [];
    for (const [key, value] of Object.entries(source)) {
      if (
        key === "image" ||
        key === "images" ||
        key === "items" ||
        key === "outputs" ||
        key === "prompt" ||
        key === "promptText" ||
        key === "promptTitle" ||
        key === "title" ||
        key === "id" ||
        key === "name" ||
        key === "displayName" ||
        key === "deploymentName"
      ) {
        continue;
      }
      if (value == null) continue;
      if (typeof value === "object") continue;
      const text = coerceText(value).trim();
      if (text) fallback.push([key, text]);
      if (fallback.length >= 4) break;
    }
    return fallback;
  }

  function parseCapability(rawModel) {
    const raw =
      rawModel?.imageInput ??
      rawModel?.image_input ??
      rawModel?.capabilities?.imageInput ??
      rawModel?.capabilities?.image_input ??
      rawModel?.capabilities?.imageEdits ??
      rawModel?.imageEdits ??
      rawModel?.supportsImageInput ??
      rawModel?.imageInputSupported ??
      rawModel?.supports_image_input ??
      rawModel?.imageInputStatus;

    if (raw === true) {
      return { status: "supported", label: "Supported", note: "Image input is available." };
    }

    if (raw === false) {
      return { status: "unsupported", label: "Unsupported", note: "Image input is not available." };
    }

    if (isObject(raw)) {
      const status = coerceText(raw.status).trim().toLowerCase();
      if ((status === "ready" || status === "supported") && raw.value === true) {
        return { status: "supported", label: "Supported", note: "Image input is available." };
      }
      if (status === "unsupported" || raw.value === false) {
        return { status: "unsupported", label: "Unsupported", note: "Image input is not available." };
      }
      if (status === "checking" || status === "pending") {
        return { status: "checking", label: "Checking", note: "The API is still reporting capability." };
      }
      if (status === "error" || raw.error) {
        return {
          status: "error",
          label: "Error",
          note: firstText(raw.error, "Capability lookup failed."),
        };
      }
    }

    if (typeof raw === "string") {
      const lower = raw.toLowerCase();
      if (lower.includes("check") || lower.includes("pending")) {
        return { status: "checking", label: "Checking", note: "The API is still reporting capability." };
      }
      if (lower.includes("error") || lower.includes("fail")) {
        return { status: "error", label: "Error", note: "Capability lookup failed." };
      }
      if (lower.includes("unsupported") || lower.includes("disabled") || lower.includes("off")) {
        return { status: "unsupported", label: "Unsupported", note: "Image input is not available." };
      }
      if (lower.includes("support")) {
        return { status: "supported", label: "Supported", note: "Image input is available." };
      }
    }

    if (isObject(raw)) {
      const rawStatus = firstText(raw.status, raw.state, raw.availability).toLowerCase();
      const message = firstText(raw.message, raw.detail, raw.reason, raw.note);
      if (rawStatus.includes("check") || rawStatus.includes("pending")) {
        return { status: "checking", label: "Checking", note: message || "The API is still reporting capability." };
      }
      if (rawStatus.includes("error") || rawStatus.includes("fail")) {
        return { status: "error", label: "Error", note: message || "Capability lookup failed." };
      }
      if (rawStatus.includes("unsupported") || rawStatus.includes("disabled") || rawStatus.includes("off")) {
        return { status: "unsupported", label: "Unsupported", note: message || "Image input is not available." };
      }
      if (rawStatus.includes("support")) {
        return { status: "supported", label: "Supported", note: message || "Image input is available." };
      }
      if (message) {
        return { status: "checking", label: "Checking", note: message };
      }
    }

    if (raw != null) {
      return {
        status: "checking",
        label: "Checking",
        note: "Image input capability is still being resolved.",
      };
    }

    return {
      status: "error",
      label: "Unavailable",
      note: "The API did not report image input capability for this model.",
    };
  }

  function parseModelsPayload(payload) {
    const list =
      (Array.isArray(payload) && payload) ||
      payload?.models ||
      payload?.items ||
      payload?.data ||
      payload?.value ||
      [];

    return toArray(list).map((item, index) => {
      const key = firstText(
        item?.id,
        item?.name,
        item?.deploymentName,
        item?.deployment,
        item?.model,
        item?.displayName,
        `model-${index + 1}`
      );
      const displayName = firstText(item?.displayName, item?.label, item?.name, item?.deploymentName, key);
      const deploymentName = firstText(item?.deploymentName, item?.deployment, item?.name, key);
      const capability = parseCapability(item);
      return {
        key,
        displayName,
        deploymentName,
        capability,
        description: firstText(item?.description, item?.summary),
        metadata: collectRenderableMetadata(item, [
          "deploymentName",
          "description",
          "defaultSettings",
          "default",
          "modelVersion",
          "version",
          "region",
        ]),
        raw: item,
      };
    });
  }

  function parseSessionPayload(payload) {
    if (!isObject(payload)) {
      return { authenticated: false, user: null };
    }
    const authenticated = payload.authenticated === true;
    const user = authenticated && isObject(payload.user)
      ? {
          name: firstText(payload.user.name, payload.user.displayName, payload.user.fullName),
          username: firstText(payload.user.username, payload.user.preferred_username, payload.user.login),
        }
      : null;
    if (!authenticated || (!user?.name && !user?.username)) {
      return { authenticated: false, user: null };
    }
    return { authenticated: true, user };
  }

  function groupGalleryPrompts(payload) {
    if (Array.isArray(payload?.prompts)) {
      const results = toArray(payload?.results);
      return payload.prompts.map((item, index) =>
        normalizePromptGroup(
          {
            ...item,
            images: results.filter(
              (result) => normalizeKey(result?.promptId) === normalizeKey(item?.id)
            ),
          },
          index
        )
      );
    }

    const source = Array.isArray(payload) ? payload : payload?.items || payload?.images || [];
    const list = toArray(source);
    if (!list.length) return DEFAULT_GALLERY_PROMPTS.map((item, index) => normalizePromptGroup(item, index));

    const grouped = new Map();
    for (const item of list) {
      const groupKey = firstText(
        item?.promptId,
        item?.promptKey,
        item?.promptIndex,
        item?.promptTitle,
        item?.prompt,
        item?.title,
        item?.label
      ) || `prompt-${grouped.size + 1}`;
      if (!grouped.has(groupKey)) {
        grouped.set(groupKey, []);
      }
      grouped.get(groupKey).push(item);
    }

    return Array.from(grouped.entries()).map(([key, items], index) =>
      normalizePromptGroup(
        {
          id: key,
          title: firstText(items[0]?.promptTitle, items[0]?.title, items[0]?.label, titleCaseFallback(index)),
          prompt: firstText(items[0]?.prompt, items[0]?.promptText, items[0]?.input, ""),
          images: items,
        },
        index
      )
    );
  }

  function normalizePromptGroup(item, index) {
    const promptText = firstText(item?.prompt, item?.promptText, item?.input, item?.text, DEFAULT_GALLERY_PROMPTS[index]?.prompt);
    const title = firstText(item?.title, item?.promptTitle, item?.label, DEFAULT_GALLERY_PROMPTS[index]?.title, titleCaseFallback(index));
    const images = toArray(item?.images || item?.outputs || item?.items || item?.results || item?.plates);
    return {
      id: firstText(item?.id, item?.key, item?.promptId, `prompt-${index + 1}`),
      title,
      prompt: promptText,
      note: firstText(item?.note, item?.description),
      metadata: collectRenderableMetadata(item, ["id", "title", "note", "promptTitle", "prompt"]),
      images: images.map((proof, proofIndex) => normalizeProof(proof, proofIndex)),
    };
  }

  function normalizeProof(item, index) {
    const metadata = collectRenderableMetadata(item, [
      "model",
      "modelName",
      "deploymentName",
      "seed",
      "resolution",
      "width",
      "height",
      "style",
      "duration",
      "durationMs",
      "id",
    ]);
    const galleryFile = firstText(item?.file);
    return {
      id: firstText(item?.id, item?.key, item?.modelId, item?.deploymentName, `proof-${index + 1}`),
      modelKey: normalizeKey(item?.modelId || item?.model || item?.deploymentName || item?.name),
      modelName: firstText(item?.modelName, item?.name, item?.displayName, item?.deploymentName, item?.modelId, `Model ${index + 1}`),
      deploymentName: firstText(item?.deploymentName, item?.model, item?.name, item?.modelId),
      promptText: firstText(item?.prompt, item?.promptText),
      src: pickUrl(item) || (galleryFile ? `/static/gallery/${galleryFile.replace(/^\/+/, "")}` : ""),
      alt: firstText(item?.alt, item?.description),
      metadata,
      raw: item,
    };
  }

  function selectGalleryProofs(promptGroup, models) {
    const byModel = new Map();
    for (const proof of promptGroup.images) {
      const key = normalizeKey(proof.modelKey || proof.deploymentName || proof.modelName);
      if (key && !byModel.has(key)) {
        byModel.set(key, proof);
      }
    }
    return models.map((model, index) => {
      const keys = [normalizeKey(model.key), normalizeKey(model.deploymentName), normalizeKey(model.displayName)];
      let proof = null;
      for (const key of keys) {
        if (key && byModel.has(key)) {
          proof = byModel.get(key);
          break;
        }
      }
      if (!proof) {
        proof = promptGroup.images[index] || null;
      }
      return proof;
    });
  }

  function normalizeDimension(value) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? Math.round(number) : 0;
  }

  function normalizeGeneratedResult(result, model, prompt, uploadFile) {
    const payload = isObject(result?.data) ? result.data : result;
    const src =
      pickUrl(payload?.image) ||
      pickUrl(payload?.output) ||
      pickUrl(payload?.result) ||
      pickUrl(payload?.generatedImage) ||
      pickUrl(payload) ||
      "";

    const blob =
      result?.blob instanceof Blob ? result.blob : payload instanceof Blob ? payload : null;

    const objectUrl = blob ? URL.createObjectURL(blob) : "";
    const finalSrc = src || objectUrl;
    const caption = firstText(
      payload?.caption,
      payload?.description,
      payload?.prompt,
      `Generated with ${model.displayName}`
    );
    const metadata = collectRenderableMetadata(payload, [
      "model",
      "modelName",
      "deploymentName",
      "seed",
      "width",
      "height",
      "durationMs",
      "style",
      "id",
    ]);
    const width = normalizeDimension(payload?.width);
    const height = normalizeDimension(payload?.height);
    return {
      id: firstText(payload?.id, `result-${Date.now()}-${Math.random().toString(16).slice(2)}`),
      modelKey: model.key,
      modelName: model.displayName,
      deploymentName: model.deploymentName,
      prompt,
      uploadFileName: uploadFile?.name || "",
      src: finalSrc,
      objectUrl: objectUrl || "",
      alt: firstText(
        payload?.alt,
        payload?.description,
        `${model.displayName} result for the current prompt`
      ),
      caption,
      metadata,
      width,
      height,
      createdAt: new Date(),
    };
  }

  function buildGenerateRequest({ model, prompt, imageFile, uploadFieldName = "image" }) {
    const body = new FormData();
    body.append("model", model.key);
    body.append("prompt", prompt);
    if (imageFile) {
      body.append(uploadFieldName, imageFile, imageFile.name || "reference-image");
    }
    return {
      url: "/api/generate",
      init: {
        method: "POST",
        body,
      },
    };
  }

  function createSessionState() {
    return {
      activeView: "gallery",
      gallery: {
        loading: true,
        error: "",
        prompts: [],
        promptIndex: 0,
        inspection: { x: 0.5, y: 0.5 },
      },
      models: {
        loading: true,
        error: "",
        items: [],
      },
      session: {
        loading: true,
        authenticated: false,
        user: null,
        error: "",
      },
      playground: {
        modelKey: "",
        prompt: "",
        uploadFile: null,
        uploadPreviewUrl: "",
        uploadPreviewName: "",
        uploadCapability: { status: "checking", label: "Checking", note: "Checking image input support…" },
        generating: false,
        generationError: "",
        results: [],
        latestResultId: "",
        generationRequest: null,
      },
      announcement: "",
      abortController: null,
    };
  }

  function resetSessionState(state, deps = {}) {
    const revoke = deps.revokeObjectURL || (typeof URL !== "undefined" && URL.revokeObjectURL ? URL.revokeObjectURL.bind(URL) : null);
    const previewUrl = state.playground.uploadPreviewUrl;
    if (previewUrl && revoke) {
      revoke(previewUrl);
    }
    for (const result of state.playground.results) {
      if (result.objectUrl && revoke) {
        revoke(result.objectUrl);
      }
    }
    if (state.abortController) {
      state.abortController.abort();
    }
    state.gallery.promptIndex = 0;
    state.gallery.inspection = { x: 0.5, y: 0.5 };
    state.playground.modelKey = "";
    state.playground.prompt = "";
    state.playground.uploadFile = null;
    state.playground.uploadPreviewUrl = "";
    state.playground.uploadPreviewName = "";
    state.playground.uploadCapability = {
      status: "checking",
      label: "Checking",
      note: "Checking image input support…",
    };
    state.playground.generating = false;
    state.playground.generationError = "";
    state.playground.results = [];
    state.playground.latestResultId = "";
    state.playground.generationRequest = null;
    state.announcement = "Current browser session cleared.";
    state.abortController = null;
  }

  function formatMetaText(entries) {
    return entries.map(([key, value]) => `${humanizeKey(key)}: ${value}`);
  }

  function humanizeKey(key) {
    return key
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/[_-]+/g, " ")
      .replace(/\b\w/g, (m) => m.toUpperCase());
  }

  function createApp(doc = typeof document !== "undefined" ? document : null, fetchImpl = typeof fetch !== "undefined" ? fetch.bind(globalThis) : null) {
    if (!doc || !fetchImpl) {
      return null;
    }

    const state = createSessionState();
    const refs = {
      viewTabs: Array.from(doc.querySelectorAll("[data-view]")),
      sessionChip: doc.getElementById("sessionChip"),
      sessionName: doc.getElementById("sessionName"),
      sessionUsername: doc.getElementById("sessionUsername"),
      signOutLink: doc.getElementById("signOutLink"),
      galleryPanel: doc.getElementById("gallery-panel"),
      playgroundPanel: doc.getElementById("playground-panel"),
      galleryState: doc.getElementById("galleryState"),
      galleryEmpty: doc.getElementById("galleryEmpty"),
      galleryError: doc.getElementById("galleryError"),
      galleryPromptLead: doc.getElementById("galleryPromptLead"),
      promptTabs: Array.from(doc.querySelectorAll("[data-prompt-index]")),
      proofGrid: doc.getElementById("proofGrid"),
      comparisonRail: doc.getElementById("comparisonRail"),
      announcement: doc.getElementById("announcement"),
      modelSelect: doc.getElementById("modelSelect"),
      capabilityCard: doc.getElementById("capabilityCard"),
      promptInput: doc.getElementById("promptInput"),
      uploadCard: doc.getElementById("uploadCard"),
      uploadNote: doc.getElementById("uploadNote"),
      uploadDropzone: doc.getElementById("uploadDropzone"),
      uploadDropzoneText: doc.getElementById("uploadDropzoneText"),
      chooseImageButton: doc.getElementById("chooseImageButton"),
      imageInput: doc.getElementById("imageInput"),
      uploadPreview: doc.getElementById("uploadPreview"),
      uploadPreviewFrame: doc.getElementById("uploadPreviewFrame"),
      clearUploadButton: doc.getElementById("clearUploadButton"),
      playgroundForm: doc.getElementById("playgroundForm"),
      generateButton: doc.getElementById("generateButton"),
      resetButton: doc.getElementById("resetButton"),
      resultState: doc.getElementById("resultState"),
      resultPreview: doc.getElementById("resultPreview"),
      resultPreviewFrame: doc.getElementById("resultPreviewFrame"),
      resultPreviewCaption: doc.getElementById("resultPreviewCaption"),
      resultHistory: doc.getElementById("resultHistory"),
    };

    function announce(text) {
      state.announcement = text;
      if (refs.announcement) {
        refs.announcement.textContent = text;
      }
    }

    function renderSessionArea() {
      const visible = state.session.authenticated && state.session.user;
      refs.sessionChip.hidden = !visible;
      if (!visible) {
        refs.sessionName.textContent = "";
        refs.sessionUsername.textContent = "";
        return;
      }
      const displayName = state.session.user.name || state.session.user.username || "User";
      const words = displayName.trim().split(/\s+/).filter(Boolean);
      const initials =
        words.length > 1
          ? `${words[0][0]}${words[words.length - 1][0]}`
          : displayName.slice(0, 2);
      refs.sessionName.textContent = initials.toUpperCase();
      refs.sessionName.setAttribute("title", displayName);
      refs.sessionUsername.textContent = state.session.user.username ? `@${state.session.user.username}` : "";
      refs.signOutLink.href = "/logout";
    }

    function setActiveView(view) {
      state.activeView = view;
      refs.galleryPanel.hidden = view !== "gallery";
      refs.playgroundPanel.hidden = view !== "playground";
      for (const button of refs.viewTabs) {
        const isActive = button.dataset.view === view;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", String(isActive));
      }
    }

    function getCurrentModels() {
      return state.models.items.length ? state.models.items : DEFAULT_MODEL_ORDER.map((modelKey, index) => ({
        key: modelKey,
        displayName: modelKey,
        deploymentName: modelKey,
        capability: {
          status: "checking",
          label: "Checking",
          note: "Loading model list…",
        },
        metadata: [],
        raw: {},
      }));
    }

    function getSelectedModel() {
      const models = getCurrentModels();
      const found = models.find((model) => model.key === state.playground.modelKey) || models[0];
      return found || null;
    }

    function updateCapabilityCard(model) {
      if (!model) {
        refs.capabilityCard.innerHTML = "";
        return;
      }
      const capability = model.capability || parseCapability(model.raw || {});
      const extra = capability.status === "supported"
        ? "You can attach one PNG or JPEG."
        : capability.status === "unsupported"
          ? "This model does not accept image input."
          : capability.status === "error"
            ? "The API did not provide a usable capability result."
            : "Capability is still being checked.";
      refs.capabilityCard.innerHTML = `
        <div class="capability-card__state" data-state="${escapeHtml(capability.status)}">
          <span class="capability-card__indicator" aria-hidden="true"></span>
          ${escapeHtml(capability.note)}
        </div>
        <p class="capability-card__hint">${escapeHtml(extra)}</p>
      `;
    }

    function updateUploadState(model) {
      const capability = model ? model.capability || parseCapability(model.raw || {}) : { status: "error", label: "Unavailable", note: "Choose a model first." };
      state.playground.uploadCapability = capability;
      refs.uploadNote.textContent = capability.note;
      const supported = capability.status === "supported";
      refs.uploadDropzone.classList.toggle("is-disabled", !supported);
      refs.imageInput.disabled = !supported;
      refs.chooseImageButton.disabled = !supported;
      refs.chooseImageButton.setAttribute("aria-disabled", String(!supported));
      refs.uploadDropzone.setAttribute("aria-disabled", String(!supported));
      refs.uploadDropzoneText.textContent = supported
        ? "Add a PNG or JPEG reference image for this model."
        : capability.status === "checking"
          ? "Wait for the capability result before adding an image."
          : capability.status === "unsupported"
            ? "This model does not accept image input."
            : capability.note || "Image input is not available.";
      if (!supported && state.playground.uploadFile) {
        clearUpload("Selected model does not support image input.");
      }
    }

    function clearUpload(reason) {
      if (state.playground.uploadPreviewUrl) {
        URL.revokeObjectURL(state.playground.uploadPreviewUrl);
      }
      state.playground.uploadFile = null;
      state.playground.uploadPreviewUrl = "";
      state.playground.uploadPreviewName = "";
      refs.imageInput.value = "";
      refs.uploadPreview.hidden = true;
      refs.uploadPreviewFrame.innerHTML = "";
      if (reason) {
        announce(reason);
      }
    }

    function canAcceptUpload() {
      return state.playground.uploadCapability.status === "supported";
    }

    function setUploadFile(file) {
      if (!file) {
        clearUpload("Upload cleared.");
        return;
      }
      if (!/^image\/(png|jpeg)$/i.test(file.type)) {
        refs.uploadNote.textContent = "Choose a PNG or JPEG.";
        announce("Unsupported file type. Choose a PNG or JPEG.");
        return;
      }
      if (state.playground.uploadPreviewUrl) {
        URL.revokeObjectURL(state.playground.uploadPreviewUrl);
      }
      const previewUrl = URL.createObjectURL(file);
      state.playground.uploadFile = file;
      state.playground.uploadPreviewUrl = previewUrl;
      state.playground.uploadPreviewName = file.name;
      refs.uploadPreview.hidden = false;
      refs.uploadPreviewFrame.innerHTML = `<img src="${escapeAttr(previewUrl)}" alt="${escapeAttr(`Reference image preview: ${file.name}`)}" />`;
      refs.uploadNote.textContent = `${file.name} selected.`;
      announce(`Reference image selected: ${file.name}.`);
    }

    function renderPromptTabs() {
      const prompts = state.gallery.prompts.length ? state.gallery.prompts : DEFAULT_GALLERY_PROMPTS;
      refs.promptTabs.forEach((button, index) => {
        const prompt = prompts[index] || DEFAULT_GALLERY_PROMPTS[index];
        const isActive = index === state.gallery.promptIndex;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-selected", String(isActive));
        button.textContent = prompt?.title || titleCaseFallback(index);
      });
      const activePrompt = prompts[state.gallery.promptIndex] || prompts[0] || DEFAULT_GALLERY_PROMPTS[0];
      refs.galleryPromptLead.textContent = activePrompt?.prompt || DEFAULT_GALLERY_PROMPTS[state.gallery.promptIndex]?.prompt || "";
    }

    function renderGallery() {
      const prompts = state.gallery.prompts.length ? state.gallery.prompts : DEFAULT_GALLERY_PROMPTS;
      const prompt = prompts[state.gallery.promptIndex] || prompts[0] || DEFAULT_GALLERY_PROMPTS[0];
      const models = getCurrentModels();

      if (state.gallery.loading) {
        refs.galleryState.textContent = "Loading gallery and model list…";
        refs.galleryEmpty.hidden = true;
        refs.galleryError.hidden = true;
        refs.proofGrid.innerHTML = Array.from({ length: 5 }, (_, index) => `
          <article class="proof-plate" aria-busy="true">
            <div class="proof-plate__head">
              <h3 class="proof-plate__title">${escapeHtml(models[index]?.displayName || DEFAULT_MODEL_ORDER[index] || `Model ${index + 1}`)}</h3>
              <div class="proof-plate__status">Loading</div>
            </div>
            <div class="proof-visual is-loading" aria-hidden="true"></div>
          </article>
        `).join("");
        return;
      }

      if (state.gallery.error) {
        refs.galleryState.textContent = "Gallery failed to load.";
        refs.galleryError.hidden = false;
        refs.galleryError.textContent = state.gallery.error;
        refs.galleryEmpty.hidden = true;
        refs.proofGrid.innerHTML = "";
        return;
      }

      refs.galleryError.hidden = true;
      refs.galleryEmpty.hidden = false;
      refs.galleryState.textContent = "";
      refs.galleryEmpty.hidden = state.gallery.prompts.length > 0;
      if (!state.gallery.prompts.length) {
        refs.galleryEmpty.hidden = false;
        refs.galleryEmpty.innerHTML = `
          <strong>No gallery proofs were returned.</strong>
          <p>The gallery endpoint did not return prompt groups.</p>
        `;
        refs.proofGrid.innerHTML = "";
        return;
      }

      const proofs = selectGalleryProofs(prompt, models);
      refs.proofGrid.innerHTML = models
        .map((model, index) => {
          const proof = proofs[index];
          const hasImage = proof && proof.src;
          const alt = proof?.alt || `AI-generated demonstration output for ${model.displayName} using the prompt “${prompt.title}”.`;
          const src = hasImage ? proof.src : "";
          const inspectStyle = `--inspect-x: ${(state.gallery.inspection.x * 100).toFixed(1)}%; --inspect-y: ${(state.gallery.inspection.y * 100).toFixed(1)}%;`;
          return `
            <article class="proof-plate" data-model-key="${escapeHtml(model.key)}">
              <div class="proof-plate__head">
                <h3 class="proof-plate__title">${escapeHtml(model.displayName)}</h3>
              </div>
              <div class="proof-visual${hasImage ? "" : " is-empty"}" style="${inspectStyle}">
                ${
                  hasImage
                    ? `<img src="${escapeAttr(src)}" alt="${escapeAttr(alt)}" loading="lazy" />`
                    : `<div>No gallery image returned for this model.</div>`
                }
                <div class="inspection-overlay" aria-hidden="true" style="${inspectStyle}">
                  <span class="inspection-overlay__dot"></span>
                </div>
              </div>
              <div class="proof-plate__actions">
                <button type="button" class="subtle-button" data-download-gallery="${index}" ${hasImage ? "" : "disabled"}>
                  Download image
                </button>
              </div>
            </article>
          `;
        })
        .join("");
    }

    function renderPlayground() {
      const models = getCurrentModels();
      const selected = getSelectedModel();
      refs.modelSelect.innerHTML = models
        .map(
          (model) =>
            `<option value="${escapeAttr(model.key)}"${model.key === selected?.key ? " selected" : ""}>${escapeHtml(model.displayName)}</option>`
        )
        .join("");

      if (state.playground.modelKey !== selected?.key) {
        state.playground.modelKey = selected?.key || "";
      }

      updateCapabilityCard(selected);
      updateUploadState(selected);
      refs.promptInput.value = state.playground.prompt;
      refs.uploadPreview.hidden = !state.playground.uploadFile;
      if (!state.playground.uploadFile) {
        refs.uploadPreviewFrame.innerHTML = "";
      }
      refs.generateButton.disabled = state.playground.generating || !state.playground.prompt.trim();
      refs.generateButton.textContent = state.playground.generating ? "Generating…" : "Generate";
      refs.resetButton.disabled = false;

      if (state.playground.generationError) {
        refs.resultState.textContent = state.playground.generationError;
        refs.resultState.dataset.state = "error";
      } else if (state.playground.generating) {
        refs.resultState.textContent = "Generating image…";
        refs.resultState.dataset.state = "loading";
      } else if (state.playground.results.length) {
        refs.resultState.textContent = `${state.playground.results.length} result${state.playground.results.length === 1 ? "" : "s"} in this session.`;
        refs.resultState.dataset.state = "ready";
      } else {
        refs.resultState.textContent = "";
        refs.resultState.dataset.state = "empty";
      }

      if (state.playground.latestResultId) {
        const latest = state.playground.results.find((item) => item.id === state.playground.latestResultId);
        if (latest && latest.src) {
          refs.resultPreview.hidden = false;
          refs.resultPreviewFrame.innerHTML = `<img src="${escapeAttr(latest.src)}" alt="${escapeAttr(latest.alt)}" />`;
          refs.resultPreviewCaption.textContent = `${latest.caption}. ${formatMetadataSummary(latest.metadata)}`.trim();
        } else {
          refs.resultPreview.hidden = true;
          refs.resultPreviewFrame.innerHTML = "";
        }
      } else {
        refs.resultPreview.hidden = true;
        refs.resultPreviewFrame.innerHTML = "";
      }

      refs.resultHistory.innerHTML = state.playground.results.length
        ? state.playground.results
            .map(
              (result) => `
                <li>
                  <div class="result-card__top">
                    <h3 class="result-card__title">${escapeHtml(result.modelName)}</h3>
                    <span class="result-meta">${escapeHtml(result.caption)}</span>
                  </div>
                  <img class="result-card__image" src="${escapeAttr(result.src)}" alt="${escapeAttr(result.alt)}" loading="lazy" />
                  <dl class="result-card__meta">
                    <div><dt>Prompt</dt><dd>${escapeHtml(result.prompt)}</dd></div>
                    ${
                      result.uploadFileName
                        ? `<div><dt>Upload</dt><dd>${escapeHtml(result.uploadFileName)}</dd></div>`
                        : ""
                    }
                    ${formatMetadataHtml(result.metadata)}
                  </dl>
                  <div class="result-card__actions">
                    <button type="button" class="subtle-button" data-download-result="${escapeAttr(result.id)}">Download result</button>
                  </div>
                </li>
              `
            )
            .join("")
        : `
          <li class="empty-copy${state.playground.generating ? " is-generating" : ""}">
            <div class="result-placeholder" aria-hidden="true">
              <svg viewBox="0 0 64 56">
                <rect x="8.5" y="7.5" width="47" height="41" rx="1.5"></rect>
                <circle cx="42" cy="20" r="4"></circle>
                <path d="m14 42 13-13 8 8 6-6 9 11"></path>
              </svg>
            </div>
            <div class="empty-copy__body">
              <strong>${state.playground.generating ? "Creating your image…" : "Your image will appear here."}</strong>
              <span>Generated results will appear here for this browser session only.</span>
            </div>
          </li>
        `;
    }

    function formatMetadataSummary(metadata) {
      if (!metadata || !metadata.length) return "";
      return metadata
        .slice(0, 2)
        .map(([key, value]) => `${humanizeKey(key)}: ${value}`)
        .join(" · ");
    }

    function formatMetadataHtml(metadata) {
      if (!metadata || !metadata.length) return "";
      return metadata
        .slice(0, 4)
        .map(([key, value]) => `<div><dt>${escapeHtml(humanizeKey(key))}</dt><dd>${escapeHtml(value)}</dd></div>`)
        .join("");
    }

    function render() {
      renderPromptTabs();
      renderSessionArea();
      renderGallery();
      renderPlayground();
      announce(state.announcement);
    }

    function setGalleryPrompt(index) {
      const max = Math.max(0, (state.gallery.prompts.length || DEFAULT_GALLERY_PROMPTS.length) - 1);
      state.gallery.promptIndex = clamp(index, 0, max);
      state.announcement = `Prompt ${state.gallery.promptIndex + 1} selected.`;
      render();
    }

    function setInspectionFromEvent(event) {
      const target = event.currentTarget.closest(".proof-plate") || event.target.closest(".proof-plate");
      if (!target) return;
      const imageBox = target.querySelector(".proof-visual");
      if (!imageBox) return;
      const rect = imageBox.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const x = clamp((event.clientX - rect.left) / rect.width, 0, 1);
      const y = clamp((event.clientY - rect.top) / rect.height, 0, 1);
      state.gallery.inspection = { x, y };
      applyInspectionPosition();
    }

    function applyInspectionPosition() {
      const x = `${(state.gallery.inspection.x * 100).toFixed(1)}%`;
      const y = `${(state.gallery.inspection.y * 100).toFixed(1)}%`;
      for (const node of refs.proofGrid.querySelectorAll(".proof-visual")) {
        node.style.setProperty("--inspect-x", x);
        node.style.setProperty("--inspect-y", y);
      }
    }

    function handleRailKeydown(event) {
      const step = event.shiftKey ? 0.1 : 0.03;
      let changed = false;
      if (event.key === "ArrowLeft") {
        state.gallery.inspection.x = clamp(state.gallery.inspection.x - step, 0, 1);
        changed = true;
      } else if (event.key === "ArrowRight") {
        state.gallery.inspection.x = clamp(state.gallery.inspection.x + step, 0, 1);
        changed = true;
      } else if (event.key === "ArrowUp") {
        state.gallery.inspection.y = clamp(state.gallery.inspection.y - step, 0, 1);
        changed = true;
      } else if (event.key === "ArrowDown") {
        state.gallery.inspection.y = clamp(state.gallery.inspection.y + step, 0, 1);
        changed = true;
      } else if (event.key === "Home") {
        state.gallery.inspection = { x: 0, y: state.gallery.inspection.y };
        changed = true;
      } else if (event.key === "End") {
        state.gallery.inspection = { x: 1, y: state.gallery.inspection.y };
        changed = true;
      } else if (event.key === "PageUp") {
        state.gallery.inspection = { x: state.gallery.inspection.x, y: clamp(state.gallery.inspection.y - 0.1, 0, 1) };
        changed = true;
      } else if (event.key === "PageDown") {
        state.gallery.inspection = { x: state.gallery.inspection.x, y: clamp(state.gallery.inspection.y + 0.1, 0, 1) };
        changed = true;
      }
      if (changed) {
        event.preventDefault();
        applyInspectionPosition();
        announce(`Inspection point ${Math.round(state.gallery.inspection.x * 100)} by ${Math.round(state.gallery.inspection.y * 100)}.`);
      }
    }

    function buildDownloadName(item, fallbackSuffix) {
      const prefix = sanitizeFileName(item.modelName || "result") || "result";
      const suffix = sanitizeFileName(fallbackSuffix || item.prompt || "image") || "image";
      return `${prefix}-${suffix}.png`;
    }

    async function downloadImage(source, filename) {
      const anchor = doc.createElement("a");
      anchor.download = filename;
      anchor.rel = "noreferrer";
      anchor.href = source;
      anchor.style.display = "none";
      doc.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    }

    function handleDownloadClick(target) {
      const galleryIndex = target.dataset.downloadGallery;
      const resultId = target.dataset.downloadResult;
      if (galleryIndex != null) {
        const model = getCurrentModels()[Number(galleryIndex)];
        const prompt = state.gallery.prompts[state.gallery.promptIndex] || DEFAULT_GALLERY_PROMPTS[0];
        const proof = selectGalleryProofs(prompt, getCurrentModels())[Number(galleryIndex)];
        if (proof?.src) {
          downloadImage(proof.src, buildDownloadName({ modelName: model?.displayName || "gallery", prompt: prompt.title }, prompt.title));
        }
        return;
      }

      if (resultId) {
        const result = state.playground.results.find((item) => item.id === resultId);
        if (result?.src) {
          downloadImage(result.src, buildDownloadName(result, result.id));
        }
      }
    }

    async function loadGallery() {
      try {
        const [galleryResponse, modelsResponse] = await Promise.all([
          fetchImpl("/api/gallery"),
          fetchImpl("/api/models"),
        ]);
        if (!galleryResponse.ok) {
          throw new Error(`Gallery request failed with status ${galleryResponse.status}.`);
        }
        if (!modelsResponse.ok) {
          throw new Error(`Model request failed with status ${modelsResponse.status}.`);
        }
        const [galleryPayload, modelsPayload] = await Promise.all([galleryResponse.json(), modelsResponse.json()]);
        state.gallery.prompts = groupGalleryPrompts(galleryPayload);
        state.models.items = parseModelsPayload(modelsPayload);
        state.models.loading = false;
        state.gallery.loading = false;
        state.gallery.error = "";
        state.models.error = "";
        if (!state.playground.modelKey) {
          state.playground.modelKey = state.models.items[0]?.key || "";
        }
        if (state.gallery.prompts.length) {
          state.gallery.promptIndex = clamp(state.gallery.promptIndex, 0, state.gallery.prompts.length - 1);
        }
        state.announcement = "Gallery and model list loaded.";
      } catch (error) {
        state.gallery.loading = false;
        state.models.loading = false;
        state.gallery.error = error instanceof Error ? error.message : "Failed to load gallery.";
        state.models.error = state.gallery.error;
        state.announcement = state.gallery.error;
      }
      render();
    }

    async function loadSession() {
      try {
        const response = await fetchImpl("/api/session");
        const contentType = response.headers.get("content-type") || "";
        if (!response.ok || !contentType.includes("application/json")) {
          state.session = { loading: false, authenticated: false, user: null, error: "" };
          render();
          return;
        }
        const payload = await response.json();
        state.session = { loading: false, ...parseSessionPayload(payload), error: "" };
      } catch {
        state.session = { loading: false, authenticated: false, user: null, error: "" };
      }
      render();
    }

    async function handleGenerate(event) {
      event.preventDefault();
      state.playground.generationError = "";
      const selected = getSelectedModel();
      const prompt = state.playground.prompt.trim();
      if (!selected) {
        state.playground.generationError = "Choose a model first.";
        render();
        return;
      }
      if (!prompt) {
        state.playground.generationError = "Write a prompt before generating.";
        render();
        return;
      }
      state.playground.generating = true;
      state.abortController = new AbortController();
      render();
      const request = buildGenerateRequest({
        model: selected,
        prompt,
        imageFile: state.playground.uploadFile,
      });
      state.playground.generationRequest = request;
      try {
        const response = await fetchImpl(request.url, { ...request.init, signal: state.abortController.signal });
        if (!response.ok) {
          throw new Error(`Generate failed with status ${response.status}.`);
        }
        let resultPayload = null;
        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("application/json")) {
          resultPayload = await response.json();
        } else if (contentType.startsWith("image/")) {
          const blob = await response.blob();
          resultPayload = { blob };
        } else {
          const text = await response.text();
          resultPayload = text.startsWith("http") || text.startsWith("data:")
            ? { image: text }
            : { caption: text };
        }
        const generated = normalizeGeneratedResult(resultPayload, selected, prompt, state.playground.uploadFile);
        state.playground.results = [generated, ...state.playground.results];
        state.playground.latestResultId = generated.id;
        state.playground.generationError = "";
        state.announcement = `Generated result for ${selected.displayName}.`;
      } catch (error) {
        if (error && error.name === "AbortError") {
          state.announcement = "Generation cancelled.";
        } else {
          state.playground.generationError = error instanceof Error ? error.message : "Generation failed.";
          state.announcement = state.playground.generationError;
        }
      } finally {
        state.playground.generating = false;
        state.abortController = null;
        render();
      }
    }

    function handleReset() {
      const revokeObjectURL =
        typeof URL !== "undefined" && typeof URL.revokeObjectURL === "function"
          ? URL.revokeObjectURL.bind(URL)
          : () => {};
      resetSessionState(state, { revokeObjectURL });
      render();
      announce(state.announcement);
    }

    function handleModelChange(event) {
      state.playground.modelKey = event.target.value;
      const selected = getSelectedModel();
      updateCapabilityCard(selected);
      updateUploadState(selected);
      render();
    }

    function handlePromptInput(event) {
      state.playground.prompt = event.target.value;
      refs.generateButton.disabled = state.playground.generating || !state.playground.prompt.trim();
    }

    function handleFileInput(event) {
      if (!canAcceptUpload()) {
        return;
      }
      const file = event.target.files && event.target.files[0];
      setUploadFile(file);
      render();
    }

    function handleDrop(event) {
      if (!canAcceptUpload()) {
        return;
      }
      event.preventDefault();
      const file = event.dataTransfer?.files?.[0];
      if (file) {
        setUploadFile(file);
        render();
      }
    }

    function handleDragOver(event) {
      if (!canAcceptUpload()) {
        return;
      }
      event.preventDefault();
    }

    refs.viewTabs.forEach((button) => {
      button.addEventListener("click", () => setActiveView(button.dataset.view));
    });

    refs.promptTabs.forEach((button) => {
      button.addEventListener("click", () => setGalleryPrompt(Number(button.dataset.promptIndex)));
      button.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        const next = event.key === "ArrowLeft" ? Number(button.dataset.promptIndex) - 1 : Number(button.dataset.promptIndex) + 1;
        setGalleryPrompt(next);
        const target = refs.promptTabs[clamp(next, 0, refs.promptTabs.length - 1)];
        target?.focus();
      });
    });

    refs.comparisonRail.addEventListener("pointermove", setInspectionFromEvent);
    refs.comparisonRail.addEventListener("pointerdown", setInspectionFromEvent);
    refs.comparisonRail.addEventListener("keydown", handleRailKeydown);
    refs.comparisonRail.addEventListener("focus", () => {
      announce("Comparison rail focused. Use arrow keys to move the inspection point.");
    });

    refs.playgroundForm.addEventListener("submit", handleGenerate);
    refs.modelSelect.addEventListener("change", handleModelChange);
    refs.promptInput.addEventListener("input", handlePromptInput);
    refs.chooseImageButton.addEventListener("click", () => {
      if (canAcceptUpload() && !refs.chooseImageButton.disabled && !refs.imageInput.disabled && typeof refs.imageInput.click === "function") {
        refs.imageInput.click();
      }
    });
    refs.imageInput.addEventListener("change", handleFileInput);
    refs.clearUploadButton.addEventListener("click", () => {
      clearUpload("Upload removed.");
      render();
    });
    refs.uploadDropzone.addEventListener("drop", handleDrop);
    refs.uploadDropzone.addEventListener("dragover", handleDragOver);
    refs.resetButton.addEventListener("click", handleReset);
    refs.proofGrid.addEventListener("click", (event) => {
      const button = event.target.closest("[data-download-gallery]");
      if (button) {
        handleDownloadClick(button);
      }
    });
    refs.resultHistory.addEventListener("click", (event) => {
      const button = event.target.closest("[data-download-result]");
      if (button) {
        handleDownloadClick(button);
      }
    });

    async function boot() {
      state.announcement = "Loading gallery and model list…";
      render();
      await Promise.all([loadGallery(), loadSession()]);
      if (!state.playground.modelKey) {
        state.playground.modelKey = state.models.items[0]?.key || "";
      }
      render();
      setActiveView("gallery");
    }

    return {
      state,
      refs,
      boot,
      render,
      setActiveView,
      setGalleryPrompt,
      handleGenerate,
      handleReset,
      setInspectionFromEvent,
      handleRailKeydown,
      clearUpload,
      setUploadFile,
    };
  }

  function escapeHtml(value) {
    return coerceText(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replace(/`/g, "&#96;");
  }

  function initialize() {
    if (typeof document === "undefined") return null;
    const app = createApp(document, typeof fetch !== "undefined" ? fetch.bind(globalThis) : null);
    if (!app) return null;
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => {
        app.boot();
      }, { once: true });
    } else {
      app.boot();
    }
    return app;
  }

  return {
    DEFAULT_MODEL_ORDER,
    DEFAULT_GALLERY_PROMPTS,
    clamp,
    toArray,
    coerceText,
    firstText,
    pickUrl,
    parseCapability,
    parseModelsPayload,
    parseSessionPayload,
    groupGalleryPrompts,
    normalizeProof,
    normalizePromptGroup,
    selectGalleryProofs,
    normalizeGeneratedResult,
    buildGenerateRequest,
    createSessionState,
    resetSessionState,
    createApp,
    initialize,
    escapeHtml,
    escapeAttr,
  };
});

if (typeof window !== "undefined") {
  window.FoundryImageModels = window.FoundryImageModels || (typeof module !== "undefined" && module.exports ? module.exports : undefined);
  window.FoundryImageModels?.initialize?.();
}
