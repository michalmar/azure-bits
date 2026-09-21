# Azure Brand Palette & Typography

## Colour palette

Use the JavaScript object below verbatim in your pptxgenjs script. Hex strings have no `#` prefix (pptxgenjs requirement).

```javascript
const C = {
  // Primary brand colours
  azureBlue:  "0000B3",  // signature Microsoft Azure blue — covers, primary accents
  deepBlue:   "0D0061",  // navy — section dividers, footer bands, card titles
  brightBlue: "1A00E2",  // electric blue — demo section, emphasis
  purple:     "5D52EC",  // process / orchestration accent
  magenta:    "D12ACA",  // action / human-trust accent
  cyan:       "00BBC3",  // data / infrastructure accent

  // Supporting neutrals
  link:       "0078D4",  // Microsoft hyperlink blue
  ink:        "1A1A1A",  // near-black for headlines on white
  body:       "404040",  // body text on white
  muted:      "808080",  // captions, footer labels
  rule:       "D9D9D6",  // thin separator lines

  // Surfaces
  cardBg:     "F4F4F8",  // default content card background
  cardBlue:   "E8EBFF",  // tinted card variant
  cardCyan:   "DFF6F7",
  cardPurple: "EEEBFB",
  cardPink:   "FAE6F8",
  white:      "FFFFFF",
  iceBlue:    "CADCFC",  // text on dark Azure-blue backgrounds
};
```

### Colour usage rules

| Surface | Use |
|---|---|
| `azureBlue` background | Cover slide only |
| `deepBlue` background | Section dividers, footer takeaway bands, dark content panels |
| `brightBlue` background | Demo / "what's next" section dividers |
| `white` background | All standard content slides |
| `cardBg` (`F4F4F8`) | Every content card, roster row, matrix cell |

### Accent rotation

When a slide has multiple cards, rotate accents in this order to keep visual variety without randomness:

```
azureBlue → purple → cyan → magenta → brightBlue → deepBlue
```

Six-card grids consume the full rotation. Four-card grids use the first four. Two-card pairs use `azureBlue` + `magenta` (opening + closing emphasis).

### Text-on-background contrast

| Background | Body text | Captions | Accent text |
|---|---|---|---|
| `white` | `body` (`404040`) | `muted` (`808080`) | `deepBlue` or accent colour |
| `cardBg` | `body` (`404040`) | `muted` (`808080`) | accent colour for tags |
| `azureBlue` / `deepBlue` / `brightBlue` | `iceBlue` (`CADCFC`) | `iceBlue` | `white` for titles |

Never put `muted` grey on `cardBg` — contrast is too low. Use `body` instead.

## Typography

### Font stack

```javascript
const FONT       = "Segoe UI";
const FONT_LIGHT = "Segoe UI Light";
const FONT_SB    = "Segoe UI Semibold";
```

Segoe UI is the Microsoft system font and is available on every Windows machine plus Microsoft 365 web/Mac clients. Do not substitute Arial, Calibri, or Helvetica — it breaks the visual identity.

### Type scale

| Element | Font | Size (pt) | Colour |
|---|---|---|---|
| Hero title (cover, thank-you) | `FONT_LIGHT` | 40–64 | `white` |
| Slide title | `FONT_LIGHT` | 26–30 | `deepBlue` |
| Section tag (above title, ALL-CAPS) | `FONT_SB` | 10 | `azureBlue`, `charSpacing: 6` |
| Card title | `FONT_SB` | 13–16 (bold) | `deepBlue` or accent |
| Body | `FONT` | 10.5–12 | `body` |
| Caption / footer label | `FONT` | 9–10 | `muted` |
| Big numeral callout | `FONT_LIGHT` | 32–44 | accent colour |
| Step number in circle | `FONT_SB` | 13–22 (bold) | `white` |
| Quote / pull text on dark | `FONT_LIGHT` | 12, italic | `white` |

### Character spacing

Use `charSpacing` (not `letterSpacing` — silently ignored by pptxgenjs):

- ALL-CAPS section tags: `charSpacing: 6`
- Cover-slide eyebrows ("Customer briefing deck"): `charSpacing: 4`
- Reusable shell band ("plan → delegate → observe …"): `charSpacing: 2`
- Hero "AZURE" wordmark on thank-you: `charSpacing: 8`

### Margins

Set `margin: 0` on every text box. pptxgenjs adds default internal padding that misaligns text from adjacent shapes and accent strips. Layouts in `patterns.md` assume zero text-box margin.

## Layout

```javascript
pres.layout = "LAYOUT_16x9";  // 10" × 5.625"
const W = 10, H = 5.625;
```

- Slide margin: 0.45" left/right, 0.7" top for title, 0.5" bottom
- Logo: top-left at `x: 0.35, y: 0.28, w: 1.0, h: 0.2`
- Footer rule: `y: H - 0.40`, height `0.012`, colour `rule`
- Footer two-digit number + section title: `y: H - 0.34`

## Don'ts

- **No `#` prefix** on hex colours — corrupts the file
- **No accent line under titles** — hallmark of AI slides; use the section-tag-above-title pattern
- **No reused option objects** across pptxgenjs calls — it mutates them in place; create fresh objects each time
- **No `ROUNDED_RECTANGLE`** when pairing with accent strips — rectangular strips don't cover rounded corners
- **No 8-character hex colours** for opacity — use the `opacity` property instead
