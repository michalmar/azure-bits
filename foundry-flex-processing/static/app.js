import { duration, money, phaseWidths, tokenCount } from "./format.mjs";

const form = document.querySelector("#benchmarkForm");
const runButton = document.querySelector("#runButton");
const runStatus = document.querySelector("#runStatus");
const prompt = document.querySelector("#prompt");
const maxOutputTokens = document.querySelector("#maxOutputTokens");
const resultSummary = document.querySelector("#resultSummary");
let config;

function activateView(name) {
  document.querySelectorAll("[data-view]").forEach((view) => {
    view.hidden = view.dataset.view !== name;
  });
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    const active = button.dataset.viewTarget === name;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  if (name === "results") void loadResults();
  window.scrollTo({ top: 0, behavior: "instant" });
}

document.querySelectorAll("[data-view-target]").forEach((button) => {
  button.addEventListener("click", () => activateView(button.dataset.viewTarget));
});

function pricePair(prices, currency) {
  return `${money(prices.input, currency)} / ${money(prices.output, currency)} per 1M`;
}

function setPricing(pricing) {
  document.querySelector("#pricingSource").textContent =
    `${pricing.source} · ${new Date(pricing.retrievedAt).toLocaleDateString()}`;
  document.querySelector("#standardPrice").textContent = pricePair(pricing.standard, pricing.currency);
  document.querySelector("#flexPrice").textContent = pricePair(pricing.flex, pricing.currency);
  document.querySelector("#pricingLink").href = pricing.pricingPageUrl;
  const warning = document.querySelector("#pricingWarning");
  warning.hidden = !pricing.warning;
  warning.textContent = pricing.warning || "";
}

function metric(label, value) {
  const term = document.createElement("dt");
  term.textContent = label;
  const detail = document.createElement("dd");
  detail.textContent = value;
  return [term, detail];
}

function renderTrack(target, latency) {
  target.replaceChildren();
  const widths = phaseWidths(latency);
  ["auth", "headers", "first", "generation"].forEach((phase, index) => {
    const segment = document.createElement("span");
    segment.dataset.phase = phase;
    segment.style.width = widths[index];
    target.append(segment);
  });
}

function renderResult(key, result, currency) {
  const total = document.querySelector(`#${key}Total`);
  const metrics = document.querySelector(`#${key}Metrics`);
  const response = document.querySelector(`#${key}Response`);
  const error = document.querySelector(`#${key}Error`);
  const track = document.querySelector(`#${key}Track`);
  const lane = track.closest(".race-lane");
  lane.dataset.state = result.ok ? "complete" : "error";
  error.hidden = true;
  metrics.replaceChildren();
  track.replaceChildren();

  if (!result.ok) {
    total.textContent = result.statusCode ? `HTTP ${result.statusCode}` : "Failed";
    response.hidden = true;
    error.hidden = false;
    error.textContent = `${result.error}${result.retryAfter ? ` Retry after ${result.retryAfter}.` : ""}`;
    return;
  }

  response.hidden = false;
  total.textContent = duration(result.latency.totalMs);
  renderTrack(track, result.latency);
  const usage = result.usage || {};
  const inputDetails = usage.input_tokens_details || {};
  const outputDetails = usage.output_tokens_details || {};
  [
    ...metric("Processed tier", result.processedTier || "unknown"),
    ...metric("Response status", result.incompleteReason || result.status || "unknown"),
    ...metric("Attempts", tokenCount(result.attempts || 1)),
    ...metric("First token", duration(result.latency.timeToFirstTokenMs)),
    ...metric("Generation", duration(result.latency.generationMs)),
    ...metric("Estimated cost", money(result.cost.amount, currency)),
    ...metric("Input tokens", tokenCount(usage.input_tokens)),
    ...metric("Cached / written", `${tokenCount(inputDetails.cached_tokens)} / ${tokenCount(inputDetails.cache_write_tokens)}`),
    ...metric("Output tokens", tokenCount(usage.output_tokens)),
    ...metric("Reasoning tokens", tokenCount(outputDetails.reasoning_tokens)),
  ].forEach((node) => metrics.append(node));
  response.replaceChildren();
  const copy = document.createElement("p");
  copy.textContent = result.outputText || "The model returned no output text.";
  response.append(copy);
}

function summarize(results, wallClockMs, currency) {
  const { standard, flex } = results;
  if (!standard.ok || !flex.ok) {
    return `Parallel run finished in ${duration(wallClockMs)}. One or more processing paths failed; inspect each lane.`;
  }
  const latencyDelta = flex.latency.totalMs - standard.latency.totalMs;
  const direction = latencyDelta >= 0 ? "slower" : "faster";
  const saved = Math.max(standard.cost.amount - flex.cost.amount, 0);
  return `Parallel run finished in ${duration(wallClockMs)}. Flex was ${duration(Math.abs(latencyDelta))} ${direction} and saved ${money(saved, currency)} for this request.`;
}

function setLoading(loading) {
  runButton.disabled = loading || !config;
  runButton.textContent = loading ? "Running both requests…" : "Run parallel comparison";
  form.setAttribute("aria-busy", String(loading));
  if (loading) {
    runStatus.textContent = "Standard and Flex requests started together. Flex can take several minutes.";
    resultSummary.textContent = "Waiting for both processing paths…";
    document.querySelectorAll(".race-lane").forEach((lane) => {
      lane.dataset.state = "loading";
      lane.querySelector(".race-lane__total").textContent = "Running…";
    });
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!form.reportValidity()) return;
  setLoading(true);
  try {
    const response = await fetch("/api/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: prompt.value,
        max_output_tokens: Number(maxOutputTokens.value),
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(payload.detail)
        ? payload.detail.map((entry) => entry.msg).join(" ")
        : payload.detail;
      throw new Error(detail || `Comparison failed (HTTP ${response.status}).`);
    }
    setPricing(payload.pricing);
    renderResult("standard", payload.results.standard, payload.pricing.currency);
    renderResult("flex", payload.results.flex, payload.pricing.currency);
    resultSummary.textContent = summarize(payload.results, payload.wallClockMs, payload.pricing.currency);
    runStatus.textContent = "Comparison complete. Change the prompt and run again.";
  } catch (error) {
    runStatus.textContent = `Comparison failed: ${error.message}`;
    resultSummary.textContent = "The comparison did not complete. Your prompt is preserved.";
  } finally {
    setLoading(false);
  }
});

fetch("/api/config")
  .then((response) => {
    if (!response.ok) throw new Error(`Configuration request failed (HTTP ${response.status}).`);
    return response.json();
  })
  .then((value) => {
    config = value;
    document.querySelector("#modelName").textContent = value.model;
    prompt.maxLength = value.maxPromptLength;
    maxOutputTokens.max = value.maxOutputTokens;
    maxOutputTokens.value = value.defaultMaxOutputTokens;
    setPricing(value.pricing);
    if (value.user) {
      document.querySelector("#readerName").textContent = value.user;
      document.querySelector("#readerName").hidden = false;
      document.querySelector("#logoutLink").hidden = false;
    }
    runButton.disabled = false;
    runStatus.textContent = "Ready. Each run sends two billable requests in parallel.";
  })
  .catch((error) => {
    runStatus.textContent = error.message;
  });

let resultsLoaded = false;

function aggregateCard(title, tier, aggregate, currency) {
  const article = document.createElement("article");
  article.className = "aggregate-card";
  article.dataset.tier = tier;
  const heading = document.createElement("div");
  heading.className = "aggregate-card__heading";
  const name = document.createElement("h2");
  name.textContent = title;
  const success = document.createElement("span");
  success.textContent = `${aggregate.successfulRuns}/${aggregate.totalRuns} completed`;
  heading.append(name, success);
  const headline = document.createElement("strong");
  headline.textContent = duration(aggregate.totalMs.p50);
  const headlineLabel = document.createElement("p");
  headlineLabel.textContent = `Median total · p95 ${duration(aggregate.totalMs.p95)}`;
  const details = document.createElement("dl");
  details.className = "aggregate-metrics";
  [
    ...metric("Median first token", duration(aggregate.timeToFirstTokenMs.p50)),
    ...metric("p95 first token", duration(aggregate.timeToFirstTokenMs.p95)),
    ...metric("Average cost", money(aggregate.averageCost, currency)),
    ...metric("Average output tokens", tokenCount(aggregate.averageOutputTokens)),
    ...metric("Total retries", tokenCount(aggregate.totalRetries)),
  ].forEach((node) => details.append(node));
  article.append(heading, headline, headlineLabel, details);
  return article;
}

function responseBlock(label, result, currency) {
  const section = document.createElement("section");
  section.className = "run-response";
  const heading = document.createElement("h4");
  heading.textContent = label;
  const metadata = document.createElement("p");
  metadata.className = "run-response__meta";
  metadata.textContent = result.ok
    ? `${duration(result.latency.totalMs)} total · ${duration(result.latency.timeToFirstTokenMs)} first token · ${money(result.cost.amount, currency)} · ${result.attempts || 1} attempt(s)`
    : `Failed after ${result.attempts || 1} attempt(s): ${result.error}`;
  const text = document.createElement("p");
  text.className = "run-response__text";
  text.textContent = result.ok ? result.outputText : result.error;
  section.append(heading, metadata, text);
  return section;
}

function runRow(run, currency) {
  const details = document.createElement("details");
  details.className = "run-row";
  const summary = document.createElement("summary");
  const label = document.createElement("strong");
  label.textContent = `Run ${run.run}`;
  const standard = document.createElement("span");
  standard.textContent = run.standard.ok ? `Standard ${duration(run.standard.latency.totalMs)}` : "Standard failed";
  const flex = document.createElement("span");
  flex.textContent = run.flex.ok ? `Flex ${duration(run.flex.latency.totalMs)}` : "Flex failed";
  const delta = document.createElement("span");
  if (run.standard.ok && run.flex.ok) {
    const difference = run.flex.latency.totalMs - run.standard.latency.totalMs;
    delta.textContent = `Flex ${duration(Math.abs(difference))} ${difference >= 0 ? "slower" : "faster"}`;
  } else {
    delta.textContent = "Incomplete pair";
  }
  summary.append(label, standard, flex, delta);
  const body = document.createElement("div");
  body.className = "run-row__body";
  body.append(
    responseBlock("Standard", run.standard, currency),
    responseBlock("Flex", run.flex, currency),
  );
  details.append(summary, body);
  return details;
}

async function loadResults() {
  if (resultsLoaded) return;
  const method = document.querySelector("#resultsMethod");
  try {
    const response = await fetch("/static/results.json");
    if (!response.ok) throw new Error(`Results request failed (HTTP ${response.status}).`);
    const payload = await response.json();
    document.querySelector("#resultsModel").textContent = payload.model;
    method.textContent =
      `${payload.runCount} sequential comparison runs · ${new Date(payload.startedAt).toLocaleString()} · ` +
      `${payload.maxOutputTokens} maximum output tokens · pricing from ${payload.pricing.source}.`;
    const aggregateGrid = document.querySelector("#aggregateGrid");
    aggregateGrid.replaceChildren(
      aggregateCard("Standard", "standard", payload.aggregate.standard, payload.pricing.currency),
      aggregateCard("Flex", "flex", payload.aggregate.flex, payload.pricing.currency),
    );
    const comparison = document.createElement("article");
    comparison.className = "aggregate-card aggregate-card--comparison";
    const title = document.createElement("h2");
    title.textContent = "Observed tradeoff";
    const headline = document.createElement("strong");
    const delta = payload.aggregate.comparison.medianLatencyDeltaPercent;
    headline.textContent = `${Math.abs(delta).toFixed(1)}%`;
    const label = document.createElement("p");
    label.textContent = `Flex median latency was ${delta >= 0 ? "higher" : "lower"}`;
    const savings = document.createElement("p");
    savings.className = "aggregate-card__note";
    savings.textContent =
      `Average estimated cost saving: ${payload.aggregate.comparison.averageCostSavingsPercent.toFixed(1)}%. ` +
      `Successful pairs: ${payload.aggregate.comparison.successfulPairs}/${payload.runCount}.`;
    comparison.append(title, headline, label, savings);
    aggregateGrid.append(comparison);
    const runsList = document.querySelector("#runsList");
    runsList.replaceChildren(...payload.runs.map((run) => runRow(run, payload.pricing.currency)));
    resultsLoaded = true;
  } catch (error) {
    method.textContent = `Benchmark results could not load: ${error.message}`;
  }
}
