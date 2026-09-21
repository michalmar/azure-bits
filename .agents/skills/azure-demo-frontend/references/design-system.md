# Design system

## Direction

The repository uses a **precision demo surface**: a quiet interface that makes
the demonstrated Azure capability, generated output, or comparison evidence the
most visually important element.

The design takes information confidence from Stripe-like product interfaces and
restraint from Apple-like utility surfaces, without copying either site. It
avoids common AI-demo tropes.

## Palette

| Role | Value | Use |
| --- | --- | --- |
| Canvas | `#FFFFFF` | Page and workspace |
| Header/action | `#111315` | Sticky header, primary action, active controls |
| Action hover | `#000000` | Primary action hover |
| Ink | `#0A2540` | Headings and primary text |
| Slate | `#425466` | Supporting text |
| Muted | `#6B7C93` | Instructions and metadata |
| Subtle surface | `#F6F9FC` | Quiet controls and empty states |
| Muted surface | `#EEF2F6` | Media placeholders |
| Hairline | `#E3E8EE` | Dividers and structure |
| Strong hairline | `#CBD5DF` | Input boundaries |
| Cyan | `#00A3C7` | Reserved supporting accent |
| Header cyan | `#6FD3E8` | Active header underline and header focus |
| Success | `#067647` | Positive capability or completed state |
| Error | `#B42318` | Errors and destructive actions |

Use color by role. Do not introduce a different primary hue for each demo.
Product output may contain any color; application chrome stays restrained.

## Typography

Use platform system fonts:

```css
font-family:
  -apple-system,
  BlinkMacSystemFont,
  "Segoe UI Variable Text",
  "Segoe UI",
  sans-serif;
```

For large display text, prefer `"Segoe UI Variable Display"` when available.

Rules:

- headings use weight `650`;
- display tracking never goes tighter than `-0.04em`;
- body line height is approximately `1.5`;
- labels use `0.84rem` to `0.88rem`, weight `650`;
- metadata uses `0.78rem` to `0.88rem`;
- body text uses ink, slate, or muted tokens rather than opacity;
- technical names wrap naturally;
- monospace is reserved for actual code, identifiers, or measurements.

Use a clear scale:

```css
h1, h2 {
  font-size: clamp(2.3rem, 4.2vw, 4.25rem);
  line-height: 0.98;
  letter-spacing: -0.04em;
}
```

Do not use a decorative eyebrow above every heading. The heading should carry
the hierarchy.

## Shell

The standard shell contains:

- a maximum content width of `1520px`;
- horizontal gutters scaling from `20px` to `64px`;
- a sticky header with a minimum height of `68px`;
- a product mark at left;
- text navigation near the center;
- optional identity and logout controls;
- a GitHub link as the final action.

The header is a solid `#111315`. Header text is white or white at 70% opacity.
The active navigation state uses a two-pixel cyan underline.

Content starts directly beneath the header. Do not insert a large generic hero
such as “Explore the future of AI.”

## Spacing

Use the base scale:

```text
4, 8, 12, 16, 24, 32, 48
```

Allow fluid gaps for large compositions:

```css
gap: clamp(46px, 6vw, 96px);
```

Keep related elements tight and separate distinct groups generously. A label,
control, and hint are one group. Input controls and output evidence are separate
groups.

## Corners and depth

Default radii:

- `2px` for image and media frames;
- `4px` for controls and small surfaces;
- `6px` for interactive drop zones and substantial placeholders.

Depth communicates material and output priority:

- use a small inset plus outer shadow on fields;
- use layered shadows on generated media and previews;
- use a restrained shadow beneath the sticky header;
- do not shadow every section;
- do not move cards upward on hover.

Recommended media shadow:

```css
box-shadow:
  0 20px 44px rgba(50, 50, 93, 0.12),
  0 3px 9px rgba(10, 37, 64, 0.06);
```

Recommended field shadow:

```css
box-shadow:
  inset 0 1px 2px rgba(10, 37, 64, 0.035),
  0 2px 5px rgba(10, 37, 64, 0.045);
```

## Navigation

Use plain text buttons or links. The active item receives an underline. Do not
put primary navigation inside pills or segmented rounded containers.

Secondary tabs may use a single baseline rule and an active near-black
underline. On narrow screens, allow horizontal scrolling instead of squeezing
labels.

## Actions

Primary:

- near-black fill;
- white text;
- at least `42px` high;
- `4px` radius;
- black hover;
- neutral gray disabled state.

Secondary:

- white fill;
- near-black text;
- inset one-pixel boundary;
- subtle-paper hover.

Destructive:

- red text;
- transparent background;
- restrained red boundary only when it improves clarity.

Do not present two actions with equal visual strength.

## Fields

Fields use:

- visible labels;
- white background;
- strong hairline border;
- `4px` radius;
- `50px` minimum control height;
- useful placeholder examples;
- supporting hints where they reduce uncertainty;
- a three-pixel near-black focus halo.

Use native `select`, `textarea`, and `input` elements. Custom visual wrappers may
add an arrow or layout treatment but must not replace native behavior.

## Media and output

Generated media is the visual centerpiece. Give it more space than controls.

Use:

- stable aspect ratios to prevent layout shift;
- muted placeholders before output exists;
- meaningful alt text;
- image-led result sections;
- flat chronological histories separated by hairlines;
- download actions in plain language.

Avoid:

- repeating the same metadata under every image;
- enclosing each output in a heavy card;
- tiny output previews beside oversized controls.

## Motion

Motion is restrained:

- active underlines: approximately `180ms`;
- routine hover/focus transitions: `150ms`;
- one optional clipped content reveal: up to `500ms`;
- loading placeholders may use a low-contrast shift or pulse.

No looping decorative header animation. No parallax. No repeated section
entrances. Reduced-motion mode removes nonessential animation.

## Responsive behavior

At approximately `820px`:

- header becomes two rows if needed;
- multi-column page heads become one column;
- workbenches stack controls above output;
- a structural hairline separates controls and output.

At approximately `560px`:

- simplify long product marks;
- allow prompt tabs to scroll horizontally;
- reduce media-placeholder size;
- keep action labels visible;
- preserve at least `20px` page gutters.

Comparison grids may switch to a horizontal snap rail below approximately
`1180px`. One comparison item should occupy most of a narrow viewport.

## Accessibility

- Meet WCAG 2.2 AA contrast.
- Preserve semantic landmarks and heading order.
- Use real buttons, links, labels, and form controls.
- Keep focus visible with a two-pixel outline and three-pixel offset.
- Use cyan focus inside the near-black header.
- Provide live regions for asynchronous generation and capability checks.
- Make custom comparisons and tabs keyboard-operable.
- Do not communicate status through color alone.
- Test at `320px`, keyboard-only, 200% zoom, and reduced motion.
