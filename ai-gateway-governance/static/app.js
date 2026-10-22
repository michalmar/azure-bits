const $ = (id) => document.getElementById(id);

const state = { config: null, busy: false };

const fmt = {
  ms: (v) => (v == null ? "—" : `${Math.round(v).toLocaleString("en-US")} ms`),
  usd: (v) => (v == null ? "—" : `$${v.toFixed(v < 0.01 ? 6 : 4)}`),
  num: (v) => (v == null ? "—" : Number(v).toLocaleString("en-US")),
  time: (iso) => (iso ? new Date(iso).toLocaleTimeString("en-GB", { hour12: false }) : "—"),
};

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value == null) continue;
    if (key === "dataset") Object.assign(node.dataset, value);
    else if (key in node) node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child != null) node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

function tone(decision) {
  if (["pass", "not_applicable"].includes(decision)) return "good";
  if (["token_limit_exceeded", "cost_limit_exceeded", "rerouted", "fallback"].includes(decision)) return "warn";
  return "bad";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  return { status: response.status, body };
}

// ---------------------------------------------------------------- config

async function loadConfig() {
  const { status, body } = await api("/api/config");
  if (status !== 200) {
    $("runStatus").textContent = "Could not load configuration.";
    return;
  }
  state.config = body;
  const gw = body.gateway;
  $("gatewayState").textContent = gw.configured ? gw.endpoint.replace("https://", "") : "not configured (.env)";
  $("gatewayState").dataset.state = gw.configured ? "ready" : "missing";
  $("primaryRoute").textContent = `${gw.primaryModel} → ${body.large.modelId}`;
  $("fallbackRoute").textContent = `${gw.fallbackModel} → ${body.small.modelId}`;
  $("directRoute").textContent = `${body.direct.endpoint.replace("https://", "")} / ${body.direct.deployment}`;
  $("burstKeyName").textContent = gw.burstKeyName;
  $("burstModel").textContent = gw.burstModel;
  const params = (p) =>
    [p.reasoningEffort && `reasoning ${p.reasoningEffort}`, p.temperature != null ? `temperature ${p.temperature}` : "default temperature"]
      .filter(Boolean)
      .join(", ");
  $("largeParams").textContent = params(body.large);
  $("smallParams").textContent = params(body.small);
  $("burstCount").max = body.maxBurst;
  $("largeCap").textContent = body.large.maxOutputTokens;
  $("smallCap").textContent = body.small.maxOutputTokens;
  setSample("short");
  $("summarizeButton").disabled = false;
  $("burstButton").disabled = !gw.burstConfigured;
  $("runStatus").textContent = gw.configured
    ? "Ready. Start with Request 1 on the direct path, then repeat via the gateway."
    : "Gateway keys are not set. The direct baseline works; see README to configure the gateway.";
}

function setSample(name) {
  const sample = state.config?.samples?.[name];
  if (!sample) return;
  $("notes").value = sample.text;
  updateCount();
}

function updateCount() {
  const chars = $("notes").value.length;
  $("charCount").textContent = `${chars.toLocaleString("en-US")} characters · roughly ${Math.round(chars / 3.2).toLocaleString("en-US")} input tokens`;
}

// ----------------------------------------------------------- run details

function renderRun(run) {
  const ok = run.status === "ok";
  const flag = $("fallbackFlag");
  if (!ok) {
    flag.dataset.state = "error";
    flag.textContent = `rejected · ${run.policy}`;
  } else if (run.fallback) {
    flag.dataset.state = "fallback";
    flag.textContent = "FALLBACK · small model";
  } else {
    flag.dataset.state = "pass";
    flag.textContent = run.path === "direct" ? "direct · no governance" : "policy pass · large model";
  }

  $("runSummary").textContent = ok
    ? run.fallback
      ? `The gateway blocked ${run.requestedModel}; the summary came from ${run.servedModel}.`
      : `Served by ${run.servedModel ?? "unknown model"}.`
    : run.error?.message ?? "Request failed.";

  const tokens = run.tokens ?? {};
  const evidence = Object.assign({}, ...(run.gatewayEvidence ?? []));
  const rows = [
    ["Status", ok ? "ok" : `error ${run.error?.httpStatus ?? ""}`.trim(), ok ? "good" : "bad"],
    ["Path", run.path === "direct" ? "direct (Entra ID, no gateway)" : "AI Gateway (api-key)"],
    ["Requested model", run.requestedModel],
    ["Served model", run.servedModel ? `${run.servedModel} (${run.servedTier})` : "—"],
    ["Fallback", run.fallback ? `yes · switched by ${run.switchedBy}` : "no", run.fallback ? "warn" : null],
    ["Policy", run.policy, tone(run.policy === "none (no gateway)" ? "not_applicable" : run.policy)],
    ["Action", run.action, run.action === "fallback" ? "warn" : run.action === "reject" ? "bad" : null],
    ["Decided by", run.decidedBy],
    ["Prompt profile", run.promptProfile ?? "—"],
    ["Tokens in / out / total", ok ? `${fmt.num(tokens.prompt)} / ${fmt.num(tokens.completion)} / ${fmt.num(tokens.total)}` : "—"],
    ["Latency (end to end)", fmt.ms(run.latencyMs)],
    ["Estimated cost", fmt.usd(run.estimatedCostUsd)],
  ];
  if (!ok && run.error?.retryAfterSeconds != null) rows.push(["Retry-After", `${run.error.retryAfterSeconds} s`]);
  for (const [key, value] of Object.entries(evidence)) {
    if (key !== "x-correlation-id") rows.push([`header: ${key}`, value]);
  }

  const dl = $("runDetails");
  dl.replaceChildren();
  for (const [label, value, t] of rows) {
    dl.append(el("dt", { textContent: label }), el("dd", { textContent: value ?? "—", dataset: t ? { tone: t } : {} }));
  }
  const links = el("dd");
  (run.auditIds ?? []).forEach((id, i) => {
    if (i) links.append(" → ");
    links.append(el("a", { href: `#audit-${id}`, textContent: id, onclick: (e) => { e.preventDefault(); showAudit(id); } }));
  });
  dl.append(el("dt", { textContent: "Audit log" }), links);

  const out = $("summaryOutput");
  out.replaceChildren(
    ok
      ? el("pre", { textContent: run.summary || "(empty response)" })
      : el("pre", { className: "error-text", textContent: JSON.stringify({ error: run.error }, null, 2) }),
  );
}

async function summarize(event) {
  event.preventDefault();
  if (state.busy) return;
  const path = new FormData($("summarizeForm")).get("path");
  setBusy(true, path === "gateway" ? "Calling AI Gateway…" : "Calling the model directly…");
  try {
    const { body } = await api("/api/summarize", {
      method: "POST",
      body: JSON.stringify({ text: $("notes").value, path }),
    });
    if (body.runId) {
      renderRun(body);
      $("runStatus").textContent = `Run ${body.runId} finished: ${body.status === "ok" ? body.policy : body.error?.code}.`;
    } else {
      $("runStatus").textContent = body.detail?.[0]?.msg ?? "Request was rejected by the app.";
    }
  } catch (error) {
    $("runStatus").textContent = `Network error: ${error.message}`;
  } finally {
    setBusy(false);
    loadAudit();
  }
}

// ----------------------------------------------------------------- burst

async function burst() {
  if (state.busy) return;
  setBusy(true, "Sending burst…");
  try {
    const count = Number($("burstCount").value) || 10;
    const { body } = await api("/api/burst", { method: "POST", body: JSON.stringify({ count }) });
    if (body.error) {
      $("runStatus").textContent = body.error.message;
      return;
    }
    $("burstResults").hidden = false;
    $("burstSummary").textContent =
      `${body.accepted} accepted, ${body.rejected} rejected for key "${body.keyName}" in ${fmt.ms(body.wallClockMs)}.` +
      (body.control ? ` Control request with key "${body.control.keyName}": HTTP ${body.control.httpStatus}.` : "");
    const strip = $("burstStrip");
    strip.replaceChildren();
    const item = (r, control) =>
      el("li", {
        title: `${r.id} · ${r.decision}`,
        dataset: { ok: String(r.httpStatus != null && r.httpStatus < 300), control: String(control) },
        textContent: control ? `ctl ${r.httpStatus ?? "ERR"}` : String(r.httpStatus ?? "ERR"),
      });
    body.requests.forEach((r) => strip.append(item(r, false)));
    if (body.control) strip.append(item(body.control, true));
    const firstError = body.requests.find((r) => r.error)?.error;
    $("burstError").textContent = firstError
      ? JSON.stringify({ error: firstError }, null, 2)
      : "No request was rejected. Lower the gateway rate limit or raise the burst size.";
    $("runStatus").textContent = `Burst ${body.runId} finished.`;
  } catch (error) {
    $("runStatus").textContent = `Network error: ${error.message}`;
  } finally {
    setBusy(false);
    loadAudit();
  }
}

// ----------------------------------------------------------------- audit

async function loadAudit() {
  const { body } = await api("/api/audit?limit=60");
  const rows = $("auditRows");
  rows.replaceChildren();
  if (!body.events?.length) {
    rows.append(el("tr", {}, el("td", { colSpan: 9, className: "empty", textContent: "No calls yet." })));
    return;
  }
  for (const e of body.events) {
    const u = e.usage ?? {};
    const served = e.servedModel ?? "—";
    rows.append(
      el(
        "tr",
        { id: `audit-${e.id}` },
        el("td", { textContent: fmt.time(e.timestamp) }),
        el("td", {}, el("button", { type: "button", textContent: e.id, onclick: () => showAudit(e.id) })),
        el("td", { textContent: `${e.path} · ${e.keyName}` }),
        el("td", { textContent: `${e.requestedModel} → ${served}` }),
        el("td", { textContent: e.httpStatus ?? "ERR", dataset: { tone: e.httpStatus && e.httpStatus < 300 ? "good" : "bad" } }),
        el("td", { textContent: e.gatewayDecision, dataset: { tone: tone(e.gatewayDecision) } }),
        el("td", { textContent: u.total_tokens != null ? `${u.prompt_tokens}+${u.completion_tokens}` : "—" }),
        el("td", { textContent: fmt.ms(e.latencyMs) }),
        el("td", { textContent: fmt.usd(e.estimatedCostUsd) }),
      ),
    );
  }
}

async function showAudit(id) {
  const { status, body } = await api(`/api/audit/${encodeURIComponent(id)}`);
  if (status !== 200) return;
  document.querySelectorAll(".audit-table tr.is-selected").forEach((r) => r.classList.remove("is-selected"));
  document.getElementById(`audit-${id}`)?.classList.add("is-selected");
  $("auditDetail").hidden = false;
  $("auditDetail").open = true;
  $("auditDetailTitle").textContent = `Raw evidence · ${id} · ${body.gatewayDecision}`;
  $("auditDetailBody").textContent = JSON.stringify(body, null, 2);
  $("auditDetail").scrollIntoView({ block: "nearest" });
}

async function clearAudit() {
  await api("/api/audit", { method: "DELETE" });
  $("auditDetail").hidden = true;
  loadAudit();
}

function setBusy(busy, message) {
  state.busy = busy;
  $("summarizeButton").disabled = busy;
  $("burstButton").disabled = busy || !state.config?.gateway?.burstConfigured;
  if (message) $("runStatus").textContent = message;
}

$("summarizeForm").addEventListener("submit", summarize);
$("burstButton").addEventListener("click", burst);
$("refreshAudit").addEventListener("click", loadAudit);
$("clearAudit").addEventListener("click", clearAudit);
$("notes").addEventListener("input", updateCount);
document.querySelectorAll("[data-sample]").forEach((b) => b.addEventListener("click", () => setSample(b.dataset.sample)));

loadConfig();
loadAudit();
