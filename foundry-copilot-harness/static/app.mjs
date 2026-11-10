export async function* readEvents(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      if (buffer.length > 4 * 1024 * 1024) throw new Error("Příliš velká událost.");
      let end;
      while ((end = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, end);
        buffer = buffer.slice(end + 1);
        if (line.trim()) yield JSON.parse(line);
      }
      if (done) break;
    }
    if (buffer.trim()) yield JSON.parse(buffer);
  } finally { reader.releaseLock(); }
}

export function safeURL(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

const SVG_NS = "http://www.w3.org/2000/svg";

const TOOL_CATALOG = {
  skill: {
    label: "Načtení postupu ze skillu",
    detail: "Aktivace verzovaného postupu workshop-planner",
    paths: ["M4 19.5A2.5 2.5 0 0 1 6.5 17H20", "M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"],
  },
  view: {
    label: "Čtení souboru v sandboxu",
    detail: "Kontrola vstupního CSV, skriptu nebo mezivýsledků",
    paths: ["M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z", "M14 2v6h6", "M8 13h8", "M8 17h5"],
  },
  shell_call: {
    label: "Spuštění Python výpočtu",
    detail: "Deterministický skript v managed sandboxu",
    paths: ["M4 17l6-6-6-6", "M12 19h8"],
  },
  web_search: {
    label: "Webové vyhledávání",
    detail: "Obecné tipy k facilitaci workshopu",
    paths: ["M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z", "M2 12h20", "M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"],
  },
  web_search_call: {
    label: "Webové vyhledávání",
    detail: "Obecné tipy k facilitaci workshopu",
    paths: ["M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z", "M2 12h20", "M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"],
  },
  apply_patch: {
    label: "Zápis reportu v pracovním prostoru",
    detail: "Sestavení doporučení recommendation.md",
    paths: ["M12 20h9", "M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"],
  },
  upload_file_from_workspace_to_foundry_project: {
    label: "Export výstupu do Foundry Files",
    detail: "Uložení souboru ke stažení z projektu",
    paths: ["M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4", "M17 8l-5-5-5 5", "M12 3v12"],
  },
};

const DEFAULT_TOOL = {
  label: "Volání nástroje v harnessu",
  detail: "Operace řízená službou Foundry",
  paths: ["M12 2v4", "M12 18v4", "M4.93 4.93l2.83 2.83", "M16.24 16.24l2.83 2.83", "M2 12h4", "M18 12h4"],
};

const STATUS_LABELS = {
  started: "Probíhá…",
  in_progress: "Zpracovává se…",
  searching: "Vyhledává na webu…",
  completed: "Hotovo",
};

function makeSvg(document, className, paths) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  if (className) svg.setAttribute("class", className);
  for (const d of paths) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

export function describeTool(name, status) {
  const info = TOOL_CATALOG[name] || DEFAULT_TOOL;
  const canonical = name === "web_search_call" ? "web_search" : (name || "tool");
  const isCompleted = status === "completed";
  return {
    canonical,
    label: info.label,
    detail: info.detail,
    paths: info.paths,
    state: isCompleted ? "completed" : "running",
    statusText: STATUS_LABELS[status] || status || "Probíhá…",
  };
}

export function upsertToolStep(document, container, steps, event) {
  const meta = describeTool(event.name, event.status);
  const key = event.id || `${meta.canonical}-${steps.size + 1}`;
  let record = steps.get(key);
  if (!record) {
    const item = document.createElement("li");
    item.className = "trace-item";
    const icon = document.createElement("span");
    icon.className = "trace-icon";
    icon.append(makeSvg(document, "", meta.paths));

    const body = document.createElement("div");
    body.className = "trace-body";
    const titleRow = document.createElement("div");
    titleRow.className = "trace-title-row";
    const label = document.createElement("span");
    label.className = "trace-label";
    label.textContent = meta.label;
    const code = document.createElement("code");
    code.className = "trace-code";
    code.textContent = meta.canonical;
    titleRow.append(label, code);

    const detail = document.createElement("span");
    detail.className = "trace-detail";
    detail.textContent = meta.detail;
    body.append(titleRow, detail);

    const badge = document.createElement("span");
    badge.className = "trace-badge";
    item.append(icon, body, badge);
    container.append(item);
    record = { item, badge, state: meta.state };
    steps.set(key, record);
  }

  record.state = meta.state;
  record.item.dataset.state = meta.state;
  record.item.dataset.tool = meta.canonical;
  record.badge.replaceChildren();
  if (meta.state === "completed") {
    record.badge.append(makeSvg(document, "trace-check", ["M20 6L9 17l-5-5"]));
  } else {
    const spinner = document.createElement("span");
    spinner.className = "trace-spinner";
    spinner.setAttribute("aria-hidden", "true");
    record.badge.append(spinner);
  }
  const text = document.createElement("span");
  text.textContent = meta.statusText;
  record.badge.append(text);
  return record;
}

export function updateTraceSummary(summaryNode, steps, active = false) {
  if (!summaryNode) return;
  const total = steps.size;
  if (!total) {
    summaryNode.hidden = true;
    summaryNode.textContent = "";
    return;
  }
  let completed = 0;
  for (const step of steps.values()) {
    if (step.state === "completed") completed += 1;
  }
  summaryNode.hidden = false;
  summaryNode.dataset.active = String(active && completed < total);
  summaryNode.textContent = completed === total && !active
    ? `${total} ${total === 1 ? "krok dokončen" : total < 5 ? "kroky dokončeny" : "kroků dokončeno"}`
    : `Krok ${Math.min(completed + 1, total)} z ${total} · ${completed} hotovo`;
}

function appendInlineMarkdown(document, parent, raw) {
  const cleaned = String(raw || "").replace(/【source:[^】]+】/g, "");
  const tokenPattern = /(\*\*([^*]+)\*\*|`([^`]+)`|https:\/\/[^\s<>()]+[^\s<>().,;:!?"'\]])/g;
  let lastIndex = 0;
  let match;
  while ((match = tokenPattern.exec(cleaned)) !== null) {
    if (match.index > lastIndex) {
      parent.append(document.createTextNode(cleaned.slice(lastIndex, match.index)));
    }
    if (match[2] !== undefined) {
      const strong = document.createElement("strong");
      strong.textContent = match[2];
      parent.append(strong);
    } else if (match[3] !== undefined) {
      const code = document.createElement("code");
      code.textContent = match[3];
      parent.append(code);
    } else {
      const href = safeURL(match[0]);
      if (href) {
        const link = document.createElement("a");
        link.href = href;
        link.textContent = href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        parent.append(link);
      } else {
        parent.append(document.createTextNode(match[0]));
      }
    }
    lastIndex = tokenPattern.lastIndex;
  }
  if (lastIndex < cleaned.length) {
    parent.append(document.createTextNode(cleaned.slice(lastIndex)));
  }
}

function splitTableCells(line) {
  return line.trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim());
}

export function renderMarkdown(document, text) {
  const fragment = document.createDocumentFragment();
  const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      continue;
    }

    if (
      line.startsWith("|") &&
      index + 1 < lines.length &&
      /^\|\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$/.test(lines[index + 1].trim())
    ) {
      const wrap = document.createElement("div");
      wrap.className = "table-wrap";
      const table = document.createElement("table");
      const headRow = table.createTHead().insertRow();
      for (const cell of splitTableCells(line)) {
        const th = document.createElement("th");
        th.scope = "col";
        appendInlineMarkdown(document, th, cell);
        headRow.append(th);
      }
      index += 2;
      const body = table.createTBody();
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        const row = body.insertRow();
        for (const cell of splitTableCells(lines[index])) {
          const td = row.insertCell();
          appendInlineMarkdown(document, td, cell);
        }
        index += 1;
      }
      wrap.append(table);
      fragment.append(wrap);
      continue;
    }

    const headingMatch = /^(#{1,4})\s+(.+)$/.exec(line);
    if (headingMatch) {
      const heading = document.createElement(headingMatch[1].length <= 2 ? "h3" : "h4");
      appendInlineMarkdown(document, heading, headingMatch[2]);
      fragment.append(heading);
      index += 1;
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const ul = document.createElement("ul");
      while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
        const li = document.createElement("li");
        appendInlineMarkdown(document, li, lines[index].trim().replace(/^[-*]\s+/, ""));
        ul.append(li);
        index += 1;
      }
      fragment.append(ul);
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      const ol = document.createElement("ol");
      while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
        const li = document.createElement("li");
        appendInlineMarkdown(document, li, lines[index].trim().replace(/^\d+\.\s+/, ""));
        ol.append(li);
        index += 1;
      }
      fragment.append(ol);
      continue;
    }

    const paragraphLines = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !lines[index].trim().startsWith("|") &&
      !/^(#{1,4}|\d+\.|[-*])\s+/.test(lines[index].trim())
    ) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    const p = document.createElement("p");
    appendInlineMarkdown(document, p, paragraphLines.join(" "));
    fragment.append(p);
  }
  return fragment;
}

export function renderBudget(document, budget) {
  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  const caption = table.createCaption();
  caption.textContent = "Ověřený výpočet z budget.json · fiktivní ceny";
  const header = table.createTHead().insertRow();
  for (const text of ["Nabídka", "Základ", "S rezervou", "Rozhodnutí"]) {
    const th = document.createElement("th");
    th.scope = "col"; th.textContent = text; header.append(th);
  }
  const reasons = { capacity: "málo míst", projector: "chybí projektor", budget: "přes limit" };
  const currency = new Intl.NumberFormat("cs-CZ", { style: "currency", currency: "CZK", maximumFractionDigits: 2 });
  const body = table.createTBody();
  for (const offer of budget.offers) {
    const row = body.insertRow();
    for (const value of [
      offer.name, currency.format(Number(offer.base_czk)), currency.format(Number(offer.total_czk)),
      offer.eligible ? "Splňuje podmínky" : offer.reasons.map(reason => reasons[reason] || reason).join(", "),
    ]) row.insertCell().textContent = value;
  }
  wrap.append(table);
  return wrap;
}

async function start() {
  const byId = id => document.getElementById(id);
  const status = (text, error = false) => {
    byId("status").textContent = text;
    byId("status").dataset.error = String(error);
  };
  let config;
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error(response.status === 401 ? "Přihlášení vypršelo. Obnovte stránku." : "Konfigurace není dostupná.");
    config = await response.json();
    byId("prompt").textContent = config.prompt;
    byId("offers").textContent = config.offers_csv;
    byId("run").disabled = !config.live;
    byId("logout").hidden = !config.live;
    status(config.live ? "Připraveno. Spuštění volá skutečného agenta ve Foundry." : "Lokální statický preview. Živé volání vyžaduje Azure hosting s managed identity.");
  } catch (error) { status(error.message, true); return; }

  byId("logout").addEventListener("click", async () => {
    try {
      const response = await fetch("/logout", { method: "POST" });
      if (!response.ok) throw new Error("Odhlášení selhalo.");
      window.location.assign("/login");
    } catch (error) { status(error.message, true); }
  });
  byId("run").addEventListener("click", async () => {
    byId("run").disabled = true;
    for (const id of ["trace", "result", "warnings", "budget", "downloads", "citations", "identifiers"]) byId(id).replaceChildren();
    const steps = new Map();
    let streamedText = "";
    updateTraceSummary(byId("trace-summary"), steps, true);
    byId("verification").textContent = "Čekám na skutečný výsledek…";
    byId("verification").dataset.verified = "false";
    status("Agent pracuje. Události přicházejí ze služby.");
    let terminal = false;
    let failed = false;
    try {
      const response = await fetch("/api/run", {
        method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": config.csrf }, body: "{}",
      });
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || `HTTP ${response.status}`);
      }
      for await (const event of readEvents(response.body)) {
        if (event.type === "accepted") {
          byId("identifiers").textContent = `Agent ${event.agent}, verze ${event.agent_version} · Conversation ${event.conversation_id}`;
        } else if (event.type === "tool") {
          upsertToolStep(document, byId("trace"), steps, event);
          updateTraceSummary(byId("trace-summary"), steps, true);
        } else if (event.type === "text") {
          streamedText += event.text;
          byId("result").replaceChildren(renderMarkdown(document, streamedText));
        } else if (event.type === "error") {
          terminal = true;
          failed = true;
          updateTraceSummary(byId("trace-summary"), steps, false);
          status(event.message, true);
        } else if (event.type === "result") {
          terminal = true;
          updateTraceSummary(byId("trace-summary"), steps, false);
          byId("result").replaceChildren(renderMarkdown(document, event.text));
          byId("verification").dataset.verified = String(event.verified);
          byId("verification").textContent = event.verified
            ? "Rozpočet souhlasí s nezávislým deterministickým výpočtem."
            : "Rozpočet není ověřený. Text agenta sám není důkaz výpočtu.";
          if (event.verified) byId("budget").append(renderBudget(document, event.budget));
          for (const warning of event.warnings) {
            const li = document.createElement("li"); li.textContent = warning; byId("warnings").append(li);
          }
          for (const file of event.files) {
            if (!file.url?.startsWith("/api/files/") || file.url.startsWith("//")) continue;
            const link = document.createElement("a");
            link.href = file.url; link.textContent = `Stáhnout ${file.filename}`; byId("downloads").append(link);
          }
          for (const citation of event.citations) {
            const url = safeURL(citation.url);
            if (!url) continue;
            const li = document.createElement("li"); const link = document.createElement("a");
            link.href = url; link.textContent = citation.title || url;
            link.target = "_blank"; link.rel = "noopener noreferrer"; li.append(link); byId("citations").append(li);
          }
          byId("identifiers").append(document.createTextNode(` · Response ${event.response_id}`));
          status(event.verified && !event.warnings.length ? "Dokončeno a ověřeno." : "Dokončeno s výhradami — podívejte se na upozornění.");
        }
      }
      if (!terminal) throw new Error("Spojení skončilo bez výsledku. Vzdálený běh může pokračovat; neopakujte jej naslepo.");
      if (!byId("trace").children.length) {
        const li = document.createElement("li");
        li.className = "empty";
        li.textContent = "Služba nevrátila detail nástrojových událostí. Zkontrolujte response trace ve Foundry.";
        byId("trace").append(li);
      }
      if (failed) byId("verification").textContent = "Běh nebyl dokončen; výsledek není ověřený.";
    } catch (error) { status(error.message, true); }
    finally { byId("run").disabled = false; }
  });
}

if (typeof document !== "undefined") start();
