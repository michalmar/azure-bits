# Design system

## Direction

**Clear comparison** makes the product mechanism visible before the interface:
one prompt, five models, five images. The visual system combines Stripe-like
information confidence with Apple-like restraint. A solid near-black header
anchors a white workspace; generated images provide the visual richness while
the interface stays exact and quiet.

The system rejects generic AI-product patterns: no glass, glow, gradient text,
floating decoration, nested cards, oversized status pills, or rounded rectangles
used as page structure.

## Color

| Token | Value | Role |
| --- | --- | --- |
| White paper | `#FFFFFF` | Workspace canvas, inputs, previews, and elevated surfaces |
| Near-black | `#111315` | Sticky header |
| Subtle paper | `#F6F9FC` | Secondary controls and quiet states |
| Ink blue | `#0A2540` | Primary text |
| Slate | `#425466` | Supporting copy |
| Muted slate | `#6B7C93` | Metadata and instructions |
| Near-black action | `#111315` | Primary action, active state, and focus |
| Cyan | `#00A3C7` | Reserved supporting accent |
| Error red | `#B42318` | Errors and destructive action |
| Success green | `#067647` | Supported capability state |
| Hairline | `#E3E8EE` | Structural rules |

Color is restrained to neutral surfaces and near-black actions. Cyan is reserved
for the active navigation line and small supporting emphasis.

## Typography

- Display: `-apple-system`, `BlinkMacSystemFont`, `Segoe UI Variable Display`,
  `Segoe UI`, sans-serif.
- Interface and body: `-apple-system`, `BlinkMacSystemFont`,
  `Segoe UI Variable Text`, `Segoe UI`, sans-serif.
- Display headings use optical system type at `650` weight, tight line height,
  and tracking no tighter than `-0.04em`.
- Body copy uses comfortable measures and slate rather than reduced opacity.
- Technical model names wrap naturally; monospace is not used as decoration.

## Layout

- Maximum content width: `1520px`.
- Horizontal gutters scale from `20px` to `64px`.
- A solid ink sticky header strip contains the product mark, Gallery/Playground
  navigation, initials avatar, logout action, and GitHub link.
- Gallery desktop: five equal image columns separated by whitespace.
- Gallery narrow screens: a large horizontal snap rail, with one model occupying
  most of the viewport.
- Playground desktop: a compact controls column and a dominant output column,
  separated by generous space rather than a container border.
- Playground mobile: controls and output stack with one structural rule.

## Components

- **Product mark:** Microsoft Foundry and Image models joined by one hairline.
- **Session identity:** a compact circular initials avatar and plain logout link.
- **GitHub link:** the GitHub mark is the final action at the far right.
- **Text navigation:** active state uses a precise two-pixel underline, not a pill.
- **Prompt selector:** horizontally adaptable tabs on one baseline.
- **Model proof:** model name, square image, synchronized inspection point, and
  text download action; no card border or repeated metadata.
- **Field:** near-square input with a single neutral outline.
- **Capability statement:** inline model support text, not a status card.
- **Upload control:** open text and action treatment; no drop-zone panel unless
  an interaction state requires one.
- **Generated result:** image-led output followed by a flat chronological list.

## Interaction and motion

- Movement is restrained to active underlines and one clipped content reveal;
  the header itself is static.
- Gallery inspection remains synchronized across every image.
- Loading uses a stable, low-contrast image placeholder.
- Hover never lifts cards or introduces colored shadows.
- Reduced-motion mode removes nonessential animation.

## Accessibility

- Meet WCAG 2.2 AA contrast for text and controls.
- Preserve semantic landmarks, tabs, forms, labels, buttons, and live regions.
- Focus uses a visible two-pixel near-black outline with a three-pixel offset;
  controls inside the dark header use cyan.
- Maintain keyboard control for view and prompt switching, comparison inspection,
  upload, generation, download, and session reset.
- Keep usable layouts at `320px`, 200% zoom, touch input, and reduced motion.

## Direction contract

<!--
THESIS: The same prompt across five models is the product; the interface refuses dashboard cards and lets evidence lead.
OWN-WORLD: White light, ink-blue type, cool gray rules, near-black actions, square-edged controls, and one thin five-model spectrum.
STORY: Understand the comparison immediately, inspect one prompt across every model, then generate, download, or clear a private session.
FIRST VIEWPORT: A sticky product strip holds view navigation, identity, logout, and GitHub; the active workspace begins immediately below it.
FORM: Precision comparison surface, balancing Stripe-like information confidence with Apple-like restraint and material simplicity.
-->
