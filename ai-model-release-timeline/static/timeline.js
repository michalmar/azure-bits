// Deterministic canvas renderer for the model release timeline.
// render(t) draws the frame for time t (seconds) and depends on nothing else,
// so the browser player and the MP4 exporter produce identical frames.

export const WIDTH = 1920;
export const HEIGHT = 1080;

const FONT =
  '-apple-system, BlinkMacSystemFont, "Segoe UI Variable Display", "Segoe UI", Inter, "Helvetica Neue", Arial, sans-serif';

const COLOR = {
  paper: "#ffffff",
  paperSubtle: "#f6f9fc",
  header: "#111315",
  ink: "#0a2540",
  slate: "#425466",
  muted: "#6b7c93",
  hairline: "#e3e8ee",
  hairlineStrong: "#cbd5df",
  cyan: "#00a3c7",
  headerCyan: "#6fd3e8",
};

const LAB_COLOR = { openai: "#0e8f6f", anthropic: "#c4623f" };
const LAB_SIDE = { openai: -1, anthropic: 1 };

const SCENE = { intro: 4, main: 60, hold: 2, zoom: 2.5, outro: 9 };
const MAIN_START = SCENE.intro;
const MAIN_END = MAIN_START + SCENE.main;
const ZOOM_START = MAIN_END + SCENE.hold;
const OUTRO_START = ZOOM_START + SCENE.zoom;
export const DURATION = OUTRO_START + SCENE.outro;

const PPD = 7; // pixels per day while the camera follows the playhead
const PLAYHEAD_X = 1300;
const AXIS_Y = 610;
const ERA_OFFSET = 24;
const ROW_BASE = 92;
const ROW_STEP = 74;
const MAX_ROWS = 4;
const LEFT = 96;
const RIGHT = WIDTH - 96;

const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
  "August", "September", "October", "November", "December"];
const DAY_MS = 86400000;

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const lerp = (a, b, k) => a + (b - a) * k;
const easeOut = (k) => 1 - Math.pow(1 - clamp(k), 3);
const easeInOut = (k) => {
  k = clamp(k);
  return k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
};
const parseDay = (iso) => Date.parse(`${iso}T00:00:00Z`);

function font(size, weight = 400) {
  return `${weight} ${size}px ${FONT}`;
}

function formatDay(ms) {
  const d = new Date(ms);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()].slice(0, 3)} ${d.getUTCFullYear()}`;
}

function withAlpha(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${clamp(alpha)})`;
}

// Constant-speed travel with short acceleration and deceleration ramps.
function travel(t, total, ramp) {
  const v = 1 / (total - ramp);
  if (t <= 0) return 0;
  if (t >= total) return 1;
  if (t < ramp) return (v * t * t) / (2 * ramp);
  if (t < total - ramp) return v * (t - ramp / 2);
  return 1 - (v * (total - t) * (total - t)) / (2 * ramp);
}

export function createTimeline(canvas, data) {
  const ctx = canvas.getContext("2d");
  canvas.width = WIDTH;
  canvas.height = HEIGHT;

  const start = parseDay(data.window.start);
  const end = parseDay(data.window.end);
  const totalDays = (end - start) / DAY_MS;
  const dayOf = (iso) => (parseDay(iso) - start) / DAY_MS;

  const releases = data.releases
    .map((r) => ({ ...r, day: dayOf(r.date), ms: parseDay(r.date) }))
    .sort((a, b) => a.day - b.day || (a.lab < b.lab ? -1 : 1));

  // Same-day launches from both labs.
  const sameDay = [];
  for (const r of releases) {
    const twin = releases.find((o) => o !== r && o.lab !== r.lab && o.day === r.day);
    if (twin && r.lab === "openai") sameDay.push({ day: r.day, openai: r, anthropic: twin });
  }

  // Label layout: greedy row assignment per lab so labels never overlap.
  const rowsEnd = { openai: [], anthropic: [] };
  for (const r of releases) {
    ctx.font = font(r.major ? 30 : 24, 650);
    const nameW = ctx.measureText(r.name).width;
    ctx.font = font(17);
    r.meta = `${formatDay(r.ms)} · ${r.note}`;
    const metaW = ctx.measureText(r.meta).width;
    r.width = Math.max(nameW, metaW) + 18;
    const x = r.day * PPD;
    const ends = rowsEnd[r.lab];
    let row = -1;
    for (let i = 0; i < MAX_ROWS; i++) {
      if ((ends[i] ?? -Infinity) + 28 <= x) { row = i; break; }
    }
    if (row < 0) row = ends.indexOf(Math.min(...ends));
    ends[row] = x + r.width;
    r.row = row;
  }

  const eras = [];
  for (const [lab, info] of Object.entries(data.labs)) {
    info.eras.forEach((e, i) => eras.push({ lab, index: i, label: e.label,
      from: dayOf(e.start), to: dayOf(e.end) + 1 }));
  }

  const counts = { openai: 0, anthropic: 0 };
  releases.forEach((r) => counts[r.lab]++);

  const quarters = [];
  for (let q = 0; q < 8; q++) {
    const qs = new Date(start); qs.setUTCMonth(qs.getUTCMonth() + q * 3);
    const qe = new Date(start); qe.setUTCMonth(qe.getUTCMonth() + q * 3 + 3);
    const inQ = releases.filter((r) => r.ms >= qs.getTime() && r.ms < qe.getTime());
    const qNum = Math.floor(qs.getUTCMonth() / 3) + 1;
    quarters.push({
      label: `Q${qNum} ’${String(qs.getUTCFullYear()).slice(2)}`,
      openai: inQ.filter((r) => r.lab === "openai").length,
      anthropic: inQ.filter((r) => r.lab === "anthropic").length,
    });
  }
  const maxQuarter = Math.max(...quarters.map((q) => Math.max(q.openai, q.anthropic)));

  // ---------------------------------------------------------------- helpers
  function text(str, x, y, { size = 20, weight = 400, color = COLOR.ink, align = "left",
    baseline = "alphabetic", alpha = 1 } = {}) {
    if (alpha <= 0) return;
    ctx.globalAlpha = clamp(alpha);
    ctx.font = font(size, weight);
    ctx.fillStyle = color;
    ctx.textAlign = align;
    ctx.textBaseline = baseline;
    ctx.fillText(str, x, y);
    ctx.globalAlpha = 1;
  }

  function line(x1, y1, x2, y2, color, width = 1, alpha = 1, dash = null) {
    if (alpha <= 0) return;
    ctx.globalAlpha = clamp(alpha);
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.setLineDash(dash || []);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }

  function dot(x, y, r, color, alpha = 1) {
    if (alpha <= 0) return;
    ctx.globalAlpha = clamp(alpha);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  function ring(x, y, r, color, width, alpha) {
    if (alpha <= 0) return;
    ctx.globalAlpha = clamp(alpha);
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  function header() {
    ctx.fillStyle = COLOR.header;
    ctx.fillRect(0, 0, WIDTH, 64);
    text("Azure Bits", LEFT, 41, { size: 20, weight: 650, color: "#ffffff" });
    ctx.font = font(20, 650);
    const w = ctx.measureText("Azure Bits").width;
    line(LEFT + w + 18, 22, LEFT + w + 18, 42, "rgba(255,255,255,0.35)");
    text("Model release timeline", LEFT + w + 36, 41, { size: 20, color: "rgba(255,255,255,0.86)" });
    let x = RIGHT;
    for (const lab of ["anthropic", "openai"]) {
      const name = data.labs[lab].name;
      ctx.font = font(18, 500);
      const tw = ctx.measureText(name).width;
      text(name, x, 40, { size: 18, weight: 500, color: "rgba(255,255,255,0.86)", align: "right" });
      dot(x - tw - 14, 34, 6, lab === "openai" ? "#3cc9a2" : "#ec9a7c");
      x -= tw + 56;
    }
  }

  // ------------------------------------------------------------- the stage
  function stage(view, playDay, labelFade, now) {
    const { originX, camDay, ppd, axisY, rowScale } = view;
    const sx = (day) => originX + (day - camDay) * ppd;
    const visible = (x, pad = 400) => x > -pad && x < WIDTH + pad;
    const nearSec = (r) => (playDay - r.day) / (totalDays / SCENE.main);

    // Era bars.
    for (const e of eras) {
      const x1 = sx(e.from);
      const x2 = Math.min(sx(e.to), sx(playDay));
      if (x2 <= x1) continue;
      const y = axisY + LAB_SIDE[e.lab] * ERA_OFFSET;
      ctx.globalAlpha = e.index % 2 ? 0.55 : 0.3;
      ctx.fillStyle = LAB_COLOR[e.lab];
      ctx.fillRect(x1 + 2, y - 3, x2 - x1 - 4, 6);
      ctx.globalAlpha = 1;
      const labelX = Math.min(Math.max(x1 + 6, 330), Math.max(x1 + 6, x2 - 200));
      const ly = y + LAB_SIDE[e.lab] * 22 + (e.lab === "anthropic" ? 6 : 0);
      text(e.label.toUpperCase(), labelX, ly, { size: 13, weight: 650, color: LAB_COLOR[e.lab],
        alpha: 0.9 * labelFade.era });
    }

    // Axis: solid for the past, dashed for the future.
    const ax0 = sx(0);
    const ax1 = sx(totalDays);
    const px = sx(playDay);
    line(Math.max(ax0, -10), axisY, Math.min(px, WIDTH + 10), axisY, COLOR.ink, 2);
    if (px < ax1) line(px, axisY, Math.min(ax1, WIDTH + 10), axisY, COLOR.hairlineStrong, 2, 1, [6, 8]);

    // Month ticks.
    for (let m = 0; m <= 24; m++) {
      const d = new Date(start); d.setUTCMonth(d.getUTCMonth() + m);
      const x = sx((d.getTime() - start) / DAY_MS);
      if (!visible(x, 60)) continue;
      const isYear = d.getUTCMonth() === 0;
      line(x, axisY - (isYear ? 10 : 5), x, axisY + (isYear ? 10 : 5), isYear ? COLOR.ink : COLOR.muted, isYear ? 2 : 1);
      if (labelFade.months > 0 && m < 24) {
        const label = isYear ? String(d.getUTCFullYear()) : MONTHS[d.getUTCMonth()].slice(0, 3).toUpperCase();
        ctx.font = font(12, 650);
        const lw = ctx.measureText(label).width;
        ctx.fillStyle = COLOR.paper;
        ctx.fillRect(x + 6, axisY - 9, lw + 8, 18);
        text(label, x + 10, axisY + 1, { size: 12, weight: 650, color: isYear ? COLOR.ink : COLOR.muted,
          baseline: "middle", alpha: labelFade.months });
      }
    }

    // Same-day bridges.
    for (const s of sameDay) {
      if (playDay < s.day) continue;
      const x = sx(s.day);
      const age = nearSec(s.openai);
      const reveal = easeOut(age / 0.6);
      const y1 = axisY - ERA_OFFSET;
      const y2 = axisY + ERA_OFFSET;
      line(x, lerp(axisY, y1, reveal), x, lerp(axisY, y2, reveal), COLOR.cyan, 4);
      const pulse = clamp(1 - (age - 2.2) / 0.8) * clamp(age / 0.3);
      if (pulse > 0 && labelFade.labels > 0.5) {
        ctx.font = font(14, 650);
        const tw = ctx.measureText("SAME DAY").width + 16;
        ctx.globalAlpha = pulse;
        ctx.fillStyle = COLOR.cyan;
        ctx.fillRect(x - tw - 12, axisY - 12, tw, 24);
        ctx.globalAlpha = 1;
        text("SAME DAY", x - tw / 2 - 12, axisY + 1, { size: 14, weight: 650, color: "#ffffff",
          align: "center", baseline: "middle", alpha: pulse });
      }
    }

    // Releases.
    for (const r of releases) {
      if (playDay < r.day) continue;
      const x = sx(r.day);
      if (!visible(x)) continue;
      const side = LAB_SIDE[r.lab];
      const color = LAB_COLOR[r.lab];
      const my = axisY + side * ERA_OFFSET;
      const age = nearSec(r);
      const pop = easeOut(age / 0.45);

      // Ripple when the playhead crosses the release.
      if (age < 1.2) {
        const k = age / 1.2;
        ring(x, my, 10 + k * (r.major ? 90 : 56), color, r.major ? 3 : 2, (1 - k) * 0.8);
      }

      const labelAlpha = pop * labelFade.labels;
      if (labelAlpha > 0) {
        const rowY = axisY + side * (ROW_BASE + r.row * ROW_STEP) * rowScale;
        const offset = (1 - pop) * 18 * side;
        const nameY = side < 0 ? rowY - 26 + offset : rowY + 30 + offset;
        const metaY = side < 0 ? rowY - 2 + offset : rowY + 54 + offset;
        const stemEnd = side < 0 ? nameY - 26 : metaY + 6;
        line(x, my + side * 8, x, lerp(my, stemEnd, pop), color, 1.5, labelAlpha);
        // White plate keeps overlapping stems from crossing the text.
        ctx.globalAlpha = labelAlpha * 0.92;
        ctx.fillStyle = COLOR.paper;
        const top = side < 0 ? nameY - (r.major ? 30 : 24) : nameY - (r.major ? 30 : 24);
        ctx.fillRect(x + 6, top, r.width, metaY - top + 8);
        ctx.globalAlpha = 1;
        text(r.name, x + 12, nameY, { size: r.major ? 30 : 24, weight: 650, color: COLOR.ink, alpha: labelAlpha });
        text(r.meta, x + 12, metaY, { size: 17, color: COLOR.slate, alpha: labelAlpha });
      }

      const radius = (r.major ? 11 : 8) * (0.6 + 0.4 * pop) * view.dotScale;
      dot(x, my, radius + 3, COLOR.paper);
      dot(x, my, radius, color);
      if (r.major) ring(x, my, radius + 6, color, 2, 0.6 * pop);

      // Compact labels for major releases in the overview.
      if (labelFade.majors > 0 && r.major) {
        const y = side < 0 ? my - 34 : my + 46;
        line(x, my + side * 14, x, y + (side < 0 ? 8 : -26), color, 1.5, labelFade.majors);
        text(r.name.replace(" + ", " / "), x, y, { size: 20, weight: 650, color: COLOR.ink,
          align: "center", alpha: labelFade.majors });
        text(formatDay(r.ms), x, y + (side < 0 ? -26 : 24), { size: 15, color: COLOR.muted,
          align: "center", alpha: labelFade.majors });
      }
    }

    // Playhead.
    if (labelFade.playhead > 0) {
      const a = labelFade.playhead;
      line(px, 250, px, 910, COLOR.header, 2, a);
      const chip = formatDay(start + playDay * DAY_MS);
      ctx.font = font(16, 650);
      const cw = ctx.measureText(chip).width + 24;
      ctx.globalAlpha = a;
      ctx.fillStyle = COLOR.header;
      ctx.fillRect(px - cw / 2, 232, cw, 30);
      ctx.globalAlpha = 1;
      text(chip, px, 248, { size: 16, weight: 650, color: "#ffffff", align: "center",
        baseline: "middle", alpha: a });
    }

    // Left fade so history scrolls out cleanly under the lane names.
    if (labelFade.edge > 0) {
      const g = ctx.createLinearGradient(0, 0, 320, 0);
      g.addColorStop(0, withAlpha(COLOR.paper, labelFade.edge));
      g.addColorStop(0.55, withAlpha(COLOR.paper, labelFade.edge * 0.92));
      g.addColorStop(1, withAlpha(COLOR.paper, 0));
      ctx.fillStyle = g;
      ctx.fillRect(0, 230, 320, 700);
      for (const lab of ["openai", "anthropic"]) {
        const y = axisY + LAB_SIDE[lab] * 150;
        dot(LEFT + 7, y - 9, 7, LAB_COLOR[lab], labelFade.edge);
        text(data.labs[lab].name, LEFT + 24, y, { size: 26, weight: 650, color: COLOR.ink,
          alpha: labelFade.edge });
      }
    }
  }

  function minimap(playDay, alpha) {
    if (alpha <= 0) return;
    const y = 1004;
    const w = RIGHT - LEFT;
    const mx = (day) => LEFT + (day / totalDays) * w;
    ctx.globalAlpha = alpha;
    line(LEFT, y, RIGHT, y, COLOR.hairlineStrong, 2, alpha);
    line(LEFT, y, mx(playDay), y, COLOR.ink, 2, alpha);
    for (let yr = 2025; yr <= 2026; yr++) {
      const x = mx((parseDay(`${yr}-01-01`) - start) / DAY_MS);
      line(x, y - 22, x, y + 22, COLOR.hairlineStrong, 1, alpha);
      text(String(yr), x + 8, y + 32, { size: 13, weight: 650, color: COLOR.muted, alpha });
    }
    for (const r of releases) {
      if (r.day > playDay) continue;
      dot(mx(r.day), y + LAB_SIDE[r.lab] * 10, r.major ? 5 : 3.5, LAB_COLOR[r.lab], alpha);
    }
    // Window currently on screen.
    const winLeft = Math.max(0, playDay - PLAYHEAD_X / PPD);
    const winRight = Math.min(totalDays, playDay + (WIDTH - PLAYHEAD_X) / PPD);
    ctx.globalAlpha = alpha * 0.08;
    ctx.fillStyle = COLOR.ink;
    ctx.fillRect(mx(winLeft), y - 20, mx(winRight) - mx(winLeft), 40);
    ctx.globalAlpha = 1;
    dot(mx(playDay), y, 5, COLOR.header, alpha);
    ctx.globalAlpha = 1;
  }

  function readout(playDay, alpha, now) {
    if (alpha <= 0) return;
    const d = new Date(start + playDay * DAY_MS);
    text(`${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`, LEFT, 168, { size: 76, weight: 650,
      color: COLOR.ink, alpha });

    // Latest release headline.
    const passed = releases.filter((r) => r.day <= playDay);
    const latestDay = passed.length ? passed[passed.length - 1].day : null;
    if (latestDay !== null) {
      const latest = passed.filter((r) => r.day === latestDay);
      const age = (playDay - latestDay) / (totalDays / SCENE.main);
      const a = easeOut(age / 0.4) * alpha;
      let x = LEFT;
      text(latest.length > 1 ? "Same day" : "Latest", x, 212, { size: 18, weight: 650,
        color: latest.length > 1 ? COLOR.cyan : COLOR.muted, alpha: a });
      x += latest.length > 1 ? 100 : 74;
      for (const r of latest) {
        dot(x + 6, 206, 6, LAB_COLOR[r.lab], a);
        text(r.name, x + 20, 212, { size: 18, weight: 500, color: COLOR.slate, alpha: a });
        ctx.font = font(18, 500);
        x += ctx.measureText(r.name).width + 48;
      }
    }

    // Running counters.
    let x = RIGHT;
    for (const lab of ["anthropic", "openai"]) {
      const lab_ = passed.filter((r) => r.lab === lab);
      const n = lab_.length;
      const last = lab_.length ? lab_[lab_.length - 1].day : -99;
      const bump = 1 + 0.12 * clamp(1 - (playDay - last) / (totalDays / SCENE.main) / 0.35);
      ctx.save();
      ctx.translate(x, 168);
      ctx.scale(bump, bump);
      text(String(n), 0, 0, { size: 76, weight: 650, color: LAB_COLOR[lab], align: "right", alpha });
      ctx.restore();
      text(`${data.labs[lab].name} releases`, x, 206, { size: 18, weight: 500, color: COLOR.muted,
        align: "right", alpha });
      x -= 250;
    }
  }

  function intro(t) {
    const fadeIn = easeOut(t / 0.8);
    const fadeOut = 1 - easeInOut((t - 3.2) / 0.8);
    const a = fadeIn * fadeOut;
    const rise = (1 - fadeIn) * 24;
    text("October 2024 – September 2026", LEFT, 380 + rise, { size: 22, weight: 650, color: COLOR.muted, alpha: a });
    text(data.title, LEFT - 4, 500 + rise, { size: 132, weight: 650, color: COLOR.ink, alpha: a });
    const sub = easeOut((t - 0.5) / 0.8) * fadeOut;
    text("Every OpenAI and Anthropic model launch, on one shared clock.", LEFT, 580, { size: 34,
      color: COLOR.slate, alpha: sub });
    const lanes = easeOut((t - 1.0) / 1.2);
    for (const lab of ["openai", "anthropic"]) {
      const y = 700 + (lab === "openai" ? 0 : 56);
      const x2 = lerp(LEFT, LEFT + 520, lanes);
      line(LEFT, y, x2, y, LAB_COLOR[lab], 6, fadeOut);
      dot(x2, y, 9, LAB_COLOR[lab], fadeOut * lanes);
      text(`${data.labs[lab].name} · ${counts[lab]} releases`, LEFT + 560, y + 8, { size: 26, weight: 650,
        color: COLOR.ink, alpha: lanes * fadeOut });
    }
  }

  function outro(t) {
    // t: seconds since OUTRO_START
    const a = (k) => easeOut((t - k) / 0.7);
    const top = 690;
    // Headline stats.
    const total = releases.length;
    const cadence = Math.round(totalDays / total);
    text(`${total} releases in 24 months`, LEFT, top + 10, { size: 48, weight: 650, color: COLOR.ink, alpha: a(0) });
    text(`One new model every ${cadence} days, on average.`, LEFT, top + 54, { size: 24,
      color: COLOR.slate, alpha: a(0.2) });
    let y = top + 120;
    for (const lab of ["openai", "anthropic"]) {
      dot(LEFT + 8, y - 9, 8, LAB_COLOR[lab], a(0.4));
      text(`${data.labs[lab].name}`, LEFT + 28, y, { size: 26, weight: 650, color: COLOR.ink, alpha: a(0.4) });
      text(String(Math.round(counts[lab] * easeOut((t - 0.4) / 1.4))), LEFT + 330, y, { size: 26,
        weight: 650, color: LAB_COLOR[lab], align: "right", alpha: a(0.4) });
      y += 44;
    }

    // Quarterly cadence chart.
    const cx = 760;
    const cw = 640;
    const base = top + 200;
    const h = 170;
    text("Releases per quarter", cx, top + 10, { size: 18, weight: 650, color: COLOR.muted, alpha: a(0.6) });
    line(cx, base, cx + cw, base, COLOR.hairlineStrong, 1, a(0.6));
    const slot = cw / quarters.length;
    quarters.forEach((q, i) => {
      const grow = easeOut((t - 0.8 - i * 0.12) / 0.8);
      const bw = 22;
      const x = cx + i * slot + slot / 2;
      for (const [j, lab] of ["openai", "anthropic"].entries()) {
        const bh = (q[lab] / maxQuarter) * h * grow;
        ctx.fillStyle = LAB_COLOR[lab];
        ctx.globalAlpha = a(0.6);
        ctx.fillRect(x - bw - 2 + j * (bw + 4), base - bh, bw, bh);
        ctx.globalAlpha = 1;
        if (grow > 0.95 && q[lab] > 0) {
          text(String(q[lab]), x - bw / 2 - 2 + j * (bw + 4), base - bh - 8, { size: 14, weight: 650,
            color: COLOR.slate, align: "center", alpha: a(0.6) });
        }
      }
      text(q.label, x, base + 26, { size: 14, weight: 650, color: COLOR.muted, align: "center", alpha: a(0.6) });
    });

    // Same-day launches.
    const sx = 1480;
    text(`${sameDay.length} same-day launches`, sx, top + 10, { size: 18, weight: 650, color: COLOR.cyan,
      alpha: a(1.4) });
    sameDay.forEach((s, i) => {
      const y0 = top + 56 + i * 76;
      const k = a(1.6 + i * 0.35);
      text(formatDay(s.openai.ms), sx, y0, { size: 16, weight: 650, color: COLOR.muted, alpha: k });
      dot(sx + 6, y0 + 20, 5, LAB_COLOR.openai, k);
      text(s.openai.name, sx + 20, y0 + 26, { size: 18, weight: 500, color: COLOR.ink, alpha: k });
      dot(sx + 6, y0 + 46, 5, LAB_COLOR.anthropic, k);
      text(s.anthropic.name, sx + 20, y0 + 52, { size: 18, weight: 500, color: COLOR.ink, alpha: k });
    });

    text(`Data as of ${formatDay(parseDay(data.asOf))}. Release dates are first public availability; sources in releases.json.`,
      LEFT, HEIGHT - 40, { size: 16, color: COLOR.muted, alpha: a(2.2) });
  }

  // ---------------------------------------------------------------- frame
  function render(tIn) {
    const t = clamp(tIn, 0, DURATION);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = COLOR.paper;
    ctx.fillRect(0, 0, WIDTH, HEIGHT);

    const mainK = travel(t - MAIN_START, SCENE.main, 1.5);
    const playDay = mainK * totalDays;
    const zoom = easeInOut((t - ZOOM_START) / SCENE.zoom);
    const appear = easeOut((t - (MAIN_START - 0.6)) / 0.9);

    if (t < MAIN_START) intro(t);

    if (t >= MAIN_START - 0.6) {
      const fitPPD = (RIGHT - LEFT) / totalDays;
      const view = {
        originX: lerp(PLAYHEAD_X, LEFT, zoom),
        camDay: lerp(playDay, 0, zoom),
        ppd: lerp(PPD, fitPPD, zoom),
        axisY: lerp(AXIS_Y, 440, zoom),
        rowScale: 1,
        dotScale: lerp(1, 0.85, zoom),
      };
      const fade = {
        labels: appear * (1 - clamp(zoom * 2.5)),
        era: appear * (1 - clamp(zoom * 2.5)),
        months: appear * (1 - clamp(zoom * 2.5)),
        playhead: appear * (1 - clamp(zoom * 3)),
        edge: appear * (1 - clamp(zoom * 3)),
        majors: clamp((zoom - 0.7) / 0.3),
      };
      ctx.globalAlpha = 1;
      // During the intro handoff the stage fades in as a whole.
      stage(view, playDay, fade, t);
      readout(playDay, appear * (1 - clamp(zoom * 3)), t);
      minimap(playDay, appear * (1 - clamp(zoom * 3)));

      if (zoom > 0) {
        // Year boundaries and overview caption.
        const k = clamp((zoom - 0.5) / 0.5);
        const sx = (day) => view.originX + (day - view.camDay) * view.ppd;
        for (const iso of ["2025-01-01", "2026-01-01"]) {
          const x = sx((parseDay(iso) - start) / DAY_MS);
          line(x, view.axisY - 150, x, view.axisY + 150, COLOR.hairlineStrong, 1, k);
          text(iso.slice(0, 4), x + 8, view.axisY - 136, { size: 16, weight: 650, color: COLOR.muted, alpha: k });
        }
        text("The whole two years at once", LEFT, 168, { size: 76, weight: 650, color: COLOR.ink, alpha: k });
        text("Each dot is a public model release.", LEFT, 212, { size: 22, color: COLOR.slate, alpha: k });
      }
    }

    if (t >= OUTRO_START) outro(t - OUTRO_START);
    header();
  }

  return { render, duration: DURATION, releases, sameDay, counts };
}
