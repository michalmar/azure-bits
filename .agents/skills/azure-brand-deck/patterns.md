# Reusable Slide Patterns

Copy-paste pptxgenjs blocks. All assume the `C`, `FONT`, `FONT_LIGHT`, `FONT_SB`, `W`, `H` constants from `palette.md` are in scope, plus the helpers below.

## Setup boilerplate

```javascript
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.title  = "Your title";
pres.author = "Microsoft";

const W = 10, H = 5.625;
const FONT = "Segoe UI", FONT_LIGHT = "Segoe UI Light", FONT_SB = "Segoe UI Semibold";
const C = { /* paste palette from palette.md */ };

const FOOTER = "Your section / theme line"; // appears in every content footer
```

## Helpers (put at top of script)

```javascript
function logo(slide, white = false) {
  slide.addImage({
    path: "working/assets/" + (white ? "ms_logo_white.png" : "ms_logo.png"),
    x: 0.35, y: 0.28, w: 1.0, h: 0.2,
  });
}

function footerBar(slide, sectionNum, sectionTitle, accent = C.azureBlue) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: H - 0.40, w: W - 0.8, h: 0.012,
    fill: { color: C.rule }, line: { color: C.rule, width: 0 },
  });
  slide.addText(String(sectionNum).padStart(2, "0"), {
    x: 0.4, y: H - 0.34, w: 0.5, h: 0.28,
    fontFace: FONT_SB, fontSize: 10, color: accent, bold: true, margin: 0,
  });
  slide.addText(sectionTitle, {
    x: 0.9, y: H - 0.34, w: 8, h: 0.28,
    fontFace: FONT, fontSize: 9, color: C.muted, margin: 0,
  });
}

function slideHeader(slide, tag, title) {
  slide.addText(tag, {
    x: 0.45, y: 0.7, w: 8, h: 0.3,
    fontFace: FONT_SB, fontSize: 10, color: C.azureBlue, bold: true, charSpacing: 6, margin: 0,
  });
  slide.addText(title, {
    x: 0.45, y: 1.0, w: 9, h: 0.6,
    fontFace: FONT_LIGHT, fontSize: 28, color: C.deepBlue, margin: 0,
  });
}
```

---

## Pattern 1 — Cover slide (dark Azure blue, decorative motifs)

```javascript
{
  const s = pres.addSlide();
  s.background = { color: C.azureBlue };

  s.addImage({ path: "working/assets/sphere_light.png",   x: 5.6, y: -0.8, w: 6.0, h: 6.0, transparency: 25 });
  s.addImage({ path: "working/assets/capsules_light.png", x: 5.0, y:  0.6, w: 5.5, h: 5.5, transparency: 55 });

  logo(s, true);

  s.addText("Microsoft Azure",       { x: 0.45, y: 0.6,  w: 5,   h: 0.35, fontFace: FONT,       fontSize: 12, color: C.iceBlue, margin: 0 });
  s.addText("Customer briefing deck",{ x: 0.45, y: 1.3,  w: 8,   h: 0.4,  fontFace: FONT,       fontSize: 13, color: C.iceBlue, charSpacing: 4, margin: 0 });
  s.addText("Your Headline Here",    { x: 0.45, y: 1.75, w: 7.5, h: 1.1,  fontFace: FONT_LIGHT, fontSize: 40, color: C.white,   margin: 0 });
  s.addText("One-sentence value prop in title case or sentence case.", {
    x: 0.45, y: 2.85, w: 7.5, h: 0.5, fontFace: FONT, fontSize: 16, color: C.iceBlue, margin: 0,
  });
  s.addText("Built with [stack you want to credit, comma separated]", {
    x: 0.45, y: 3.4, w: 7.5, h: 0.4, fontFace: FONT, fontSize: 11, color: C.iceBlue, italic: true, margin: 0,
  });

  // Three stat callouts
  const stats = [
    { n: "4", l: "specialist agents" },
    { n: "1", l: "shared scratchpad" },
    { n: "5", l: "visible workflow steps" },
  ];
  stats.forEach((it, i) => {
    const x = 0.45 + i * 1.7;
    s.addText(it.n, { x, y: 4.05, w: 1.5, h: 0.7, fontFace: FONT_LIGHT, fontSize: 44, color: C.white,   margin: 0 });
    s.addText(it.l, { x, y: 4.78, w: 1.7, h: 0.3, fontFace: FONT,       fontSize: 10, color: C.iceBlue, margin: 0 });
  });

  // Bottom takeaway strip
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: H - 0.5, w: W, h: 0.5, fill: { color: C.deepBlue }, line: { color: C.deepBlue, width: 0 },
  });
  s.addText("Use case: one-line subject of the deck", {
    x: 0.45, y: H - 0.46, w: W - 0.9, h: 0.42,
    fontFace: FONT, fontSize: 10, color: C.iceBlue, valign: "middle", margin: 0,
  });
}
```

---

## Pattern 2 — Three-pillar concept card (white background)

```javascript
{
  const s = pres.addSlide();
  s.background = { color: C.white };
  logo(s);
  slideHeader(s, "PLAIN-LANGUAGE FRAMING", "What is X?");

  s.addText("One- or two-paragraph plain-language explanation that sets up the three pillars below.", {
    x: 0.45, y: 1.75, w: 9.1, h: 0.6, fontFace: FONT, fontSize: 12, color: C.body, margin: 0,
  });

  const pillars = [
    { tag: "Pillar A", color: C.azureBlue, body: "Short definition of pillar A." },
    { tag: "Pillar B", color: C.purple,    body: "Short definition of pillar B." },
    { tag: "Pillar C", color: C.cyan,      body: "Short definition of pillar C." },
  ];
  const py = 3.15, ph = 1.9, pw = 3.0, gap = 0.2;
  pillars.forEach((p, i) => {
    const x = 0.45 + i * (pw + gap);
    s.addShape(pres.shapes.RECTANGLE, { x, y: py, w: pw, h: ph,    fill: { color: C.cardBg }, line: { color: C.cardBg, width: 0 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y: py, w: pw, h: 0.08,  fill: { color: p.color  }, line: { color: p.color,  width: 0 } });
    s.addText(p.tag,  { x: x + 0.25, y: py + 0.25, w: pw - 0.5, h: 0.4, fontFace: FONT_SB, fontSize: 16, color: p.color, bold: true, margin: 0 });
    s.addText(p.body, { x: x + 0.25, y: py + 0.7,  w: pw - 0.5, h: 1.1, fontFace: FONT,    fontSize: 11, color: C.body,  margin: 0 });
  });

  footerBar(s, 2, FOOTER);
}
```

---

## Pattern 3 — 2×3 numbered concept grid

```javascript
const concepts = [
  { n: "1", t: "Concept",  c: C.azureBlue,  b: "Description." },
  { n: "2", t: "Concept",  c: C.purple,     b: "Description." },
  { n: "3", t: "Concept",  c: C.cyan,       b: "Description." },
  { n: "4", t: "Concept",  c: C.brightBlue, b: "Description." },
  { n: "5", t: "Concept",  c: C.magenta,    b: "Description." },
  { n: "6", t: "Concept",  c: C.deepBlue,   b: "Description." },
];
const gx = 0.45, gy = 1.95, cw = 3.0, ch = 1.55, gap = 0.15;
concepts.forEach((it, i) => {
  const row = Math.floor(i / 3), col = i % 3;
  const x = gx + col * (cw + gap), y = gy + row * (ch + gap);
  s.addShape(pres.shapes.RECTANGLE, { x, y, w: cw, h: ch, fill: { color: C.cardBg }, line: { color: C.cardBg, width: 0 } });
  s.addShape(pres.shapes.OVAL,      { x: x + 0.2, y: y + 0.2, w: 0.45, h: 0.45, fill: { color: it.c }, line: { color: it.c, width: 0 } });
  s.addText(it.n, { x: x + 0.2,  y: y + 0.2,  w: 0.45,    h: 0.45,        fontFace: FONT_SB, fontSize: 14,  color: C.white,    bold: true, align: "center", valign: "middle", margin: 0 });
  s.addText(it.t, { x: x + 0.75, y: y + 0.22, w: cw - 0.9, h: 0.4,        fontFace: FONT_SB, fontSize: 14,  color: C.deepBlue, bold: true, margin: 0 });
  s.addText(it.b, { x: x + 0.2,  y: y + 0.78, w: cw - 0.4, h: ch - 0.85,  fontFace: FONT,    fontSize: 10.5, color: C.body,    margin: 0 });
});
```

---

## Pattern 4 — Roster of feature/agent rows (one card per row)

```javascript
const items = [
  { n: "1", t: "Item title", src: "Source / source-system label", c: C.azureBlue, b: "Description of what this item provides." },
  { n: "2", t: "Item title", src: "Source / source-system label", c: C.purple,    b: "Description." },
  { n: "3", t: "Item title", src: "Source / source-system label", c: C.cyan,      b: "Description." },
  { n: "4", t: "Item title", src: "Source / source-system label", c: C.magenta,   b: "Description." },
];
const gy = 1.85, rh = 0.66, rgap = 0.1;
items.forEach((it, i) => {
  const y = gy + i * (rh + rgap);
  s.addShape(pres.shapes.RECTANGLE, { x: 0.45, y, w: W - 0.9, h: rh,   fill: { color: C.cardBg }, line: { color: C.cardBg, width: 0 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.45, y, w: 0.07,    h: rh,   fill: { color: it.c },     line: { color: it.c,     width: 0 } });
  s.addShape(pres.shapes.OVAL,      { x: 0.68, y: y + 0.13, w: 0.42, h: 0.42, fill: { color: it.c }, line: { color: it.c, width: 0 } });
  s.addText(it.n,   { x: 0.68, y: y + 0.13, w: 0.42, h: 0.42,           fontFace: FONT_SB, fontSize: 14,  color: C.white,    bold: true, align: "center", valign: "middle", margin: 0 });
  s.addText(it.t,   { x: 1.3,  y: y + 0.08, w: 2.6,  h: 0.3,            fontFace: FONT_SB, fontSize: 13,  color: C.deepBlue, bold: true, margin: 0 });
  s.addText(it.src, { x: 1.3,  y: y + 0.36, w: 2.6,  h: 0.25,           fontFace: FONT,    fontSize: 9.5, color: it.c,       margin: 0 });
  s.addText(it.b,   { x: 4.0,  y: y + 0.1,  w: 5.55, h: rh - 0.15,      fontFace: FONT,    fontSize: 10.5, color: C.body,    valign: "middle", margin: 0 });
});
```

---

## Pattern 5 — Five-step horizontal flow

```javascript
const steps = [
  { v: "Step",  c: C.azureBlue,  b: "Short description." },
  { v: "Step",  c: C.brightBlue, b: "Short description." },
  { v: "Step",  c: C.purple,     b: "Short description." },
  { v: "Step",  c: C.magenta,    b: "Short description." },
  { v: "Step",  c: C.cyan,       b: "Short description." },
];
const sx = 0.45, sy = 2.05, sw = 1.78, gap = 0.12;
s.addShape(pres.shapes.LINE, {
  x: sx + 0.5, y: sy + 0.5, w: 5 * (sw + gap) - 1 - gap, h: 0,
  line: { color: C.rule, width: 1, dashType: "dash" },
});
steps.forEach((it, i) => {
  const x = sx + i * (sw + gap);
  s.addShape(pres.shapes.OVAL, { x: x + 0.65, y: sy + 0.15, w: 0.7, h: 0.7, fill: { color: it.c }, line: { color: it.c, width: 0 } });
  s.addText(String(i + 1), { x: x + 0.65, y: sy + 0.15, w: 0.7,  h: 0.7,  fontFace: FONT_SB, fontSize: 22, color: C.white,    bold: true, align: "center", valign: "middle", margin: 0 });
  s.addText(it.v,          { x,           y: sy + 0.95, w: sw,   h: 0.35, fontFace: FONT_SB, fontSize: 15, color: C.deepBlue, bold: true, align: "center", margin: 0 });
  s.addText(it.b,          { x: x + 0.1,  y: sy + 1.30, w: sw - 0.2, h: 0.55, fontFace: FONT, fontSize: 10, color: C.body,   align: "center", margin: 0 });
});
```

---

## Pattern 6 — Section divider (dark, motif-decorated)

```javascript
{
  const s = pres.addSlide();
  s.background = { color: C.deepBlue };  // or C.brightBlue for a second divider
  s.addImage({ path: "working/assets/capsules_purple.png", x: 4.8, y: 0.3, w: 5.5, h: 5.5, transparency: 30 });
  s.addImage({ path: "working/assets/sphere_purple.png",   x: 5.8, y: 1.5, w: 4.5, h: 4.5, transparency: 35 });

  logo(s, true);
  s.addText("Section",       { x: 0.45, y: 2.2,  w: 4, h: 0.4, fontFace: FONT,       fontSize: 13, color: C.iceBlue, charSpacing: 4, margin: 0 });
  s.addText("Architecture",  { x: 0.45, y: 2.55, w: 7, h: 1.1, fontFace: FONT_LIGHT, fontSize: 54, color: C.white,   margin: 0 });
  s.addText("One-line description of what's in this section.", {
    x: 0.45, y: 3.85, w: 5, h: 0.7, fontFace: FONT, fontSize: 14, color: C.iceBlue, margin: 0,
  });

  footerBar(s, 9, FOOTER, C.cyan);
}
```

---

## Pattern 7 — Architecture matrix (5 columns with header bands)

```javascript
const cols = [
  { h: "Column A", c: C.azureBlue,  items: ["Item", "Item", "Item"] },
  { h: "Column B", c: C.brightBlue, items: ["Item", "Item", "Item"] },
  { h: "Column C", c: C.purple,     items: ["Item", "Item", "Item"] },
  { h: "Column D", c: C.magenta,    items: ["Item", "Item", "Item"] },
  { h: "Column E", c: C.cyan,       items: ["Item", "Item", "Item"] },
];
const totalW = W - 0.9, gap = 0.1;
const cw = (totalW - gap * (cols.length - 1)) / cols.length;
const top = 1.75;
cols.forEach((col, i) => {
  const x = 0.45 + i * (cw + gap);
  s.addShape(pres.shapes.RECTANGLE, { x, y: top,       w: cw, h: 0.5,  fill: { color: col.c },  line: { color: col.c, width: 0 } });
  s.addText(col.h, { x: x + 0.08, y: top, w: cw - 0.16, h: 0.5, fontFace: FONT_SB, fontSize: 11.5, color: C.white, bold: true, valign: "middle", margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x, y: top + 0.5, w: cw, h: 2.35, fill: { color: C.cardBg }, line: { color: C.cardBg, width: 0 } });
  col.items.forEach((it, j) => {
    const y = top + 0.6 + j * 0.7;
    s.addShape(pres.shapes.OVAL, { x: x + 0.12, y: y + 0.18, w: 0.12, h: 0.12, fill: { color: col.c }, line: { color: col.c, width: 0 } });
    s.addText(it, { x: x + 0.3, y, w: cw - 0.35, h: 0.55, fontFace: FONT, fontSize: 10.5, color: C.body, valign: "middle", margin: 0 });
  });
});
```

---

## Pattern 8 — Thank-you slide

```javascript
{
  const s = pres.addSlide();
  s.background = { color: C.deepBlue };

  s.addImage({ path: "working/assets/sphere_purple.png", x: 5.3, y: 0.4, w: 5.2, h: 5.2, transparency: 20 });
  s.addText("AZURE", {
    x: 5.0, y: 0.55, w: 4.7, h: 0.9,
    fontFace: FONT_LIGHT, fontSize: 54, color: C.brightBlue, margin: 0, charSpacing: 8, align: "right", valign: "middle",
  });

  logo(s, true);

  s.addText("Thank you", { x: 0.45, y: 2.2,  w: 6, h: 1.4,  fontFace: FONT_LIGHT, fontSize: 64, color: C.white,   margin: 0 });
  s.addText("Deck title", { x: 0.45, y: 3.55, w: 6, h: 0.45, fontFace: FONT,       fontSize: 16, color: C.iceBlue, margin: 0 });
  s.addText("Built on [stack credit line].", {
    x: 0.45, y: 4.0, w: 6, h: 0.5, fontFace: FONT, fontSize: 11, color: C.iceBlue, italic: true, margin: 0,
  });

  s.addShape(pres.shapes.LINE, { x: 0.45, y: 4.75, w: 5.5, h: 0, line: { color: C.cyan, width: 1.5 } });
  s.addText("Presenter Name  ·  Title  ·  Microsoft", {
    x: 0.45, y: 4.85, w: 6, h: 0.35, fontFace: FONT, fontSize: 11, color: C.iceBlue, margin: 0,
  });
}
```

---

## Closing the script

```javascript
pres.writeFile({ fileName: "output/Your_Deck_Name.pptx" })
  .then((f) => console.log("WROTE:", f));
```

The file MUST land in `output/` for the user to see it. The `pptx` skill's QA pipeline picks it up from there.

## Common deck structure (15 slides, proven layout)

1. Cover (Pattern 1)
2. Plain-language framing — three pillars (Pattern 2)
3. Core concepts — 2×3 grid (Pattern 3)
4. Business value — four numbered cards
5. Use-case / scenario — quote panel + four output cards
6. Domain portability — five short cards
7. Roster of features/agents (Pattern 4)
8. Experience flow — five steps (Pattern 5)
9. Section divider: Architecture (Pattern 6)
10. Architecture variation A — layered reference
11. Architecture variation B — identity / data flow
12. Architecture variation C — solution blueprint matrix (Pattern 7)
13. Section divider: Demo (Pattern 6, `brightBlue` background)
14. Demo walkthrough — numbered steps + takeaway cards
15. Thank you (Pattern 8)
