---
name: azure-demo-frontend
description: Create, redesign, or polish small frontend demos in the azure-bits repository using its shared visual language: white canvas, near-black sticky header, ink-blue editorial typography, restrained cyan emphasis, low-radius controls, image-led layouts, and accessible responsive behavior. Use for new demo pages, galleries, playgrounds, comparison tools, forms, and customer-facing proof-of-concept interfaces that should match the repository's other demos.
license: MIT
---

# Azure demo frontend

Build small customer-facing demo interfaces that feel like one product family.
The reference implementation is `foundry-image-models`, but this skill captures
the reusable system rather than its model-specific content.

## Design contract

Every demo should feel:

- precise rather than decorative;
- modern without resembling a generic AI dashboard;
- light, editorial, and content-led;
- credible enough for a customer briefing;
- simple enough that the demonstrated Azure capability remains the focus.

The stable visual relationship is:

1. a solid near-black sticky header;
2. a pure white workspace;
3. ink-blue text and cool gray structure;
4. near-black primary actions;
5. cyan used sparingly for navigation or supporting emphasis;
6. generated media, diagrams, or real product output providing the visual color.

Do not replace this relationship with a new theme for each demo.

## Start here

Read these references before editing:

- [Design system](references/design-system.md)
- [Reusable patterns](references/patterns.md)
- [Validation checklist](references/validation.md)

Copy these assets into the demo's own frontend folder, then adapt them:

- `assets/tokens.css`
- `assets/baseline.css`

Do not load runtime assets directly from `.agents/skills`. Each demo must remain
self-contained inside its top-level folder.

## Workflow

1. **Inspect the demo and its task.**
   Identify the primary customer action, the most important output, required
   states, and whether the surface is primarily a gallery, playground,
   comparison, form, or read-only explanation.
2. **Reuse the repository baseline.**
   Check existing demo styles before adding tokens or components. Copy the
   provided assets only when the demo does not already contain an equivalent
   baseline.
3. **Write one visual thesis.**
   State what evidence or output should dominate the page. The interface should
   recede behind that evidence.
4. **Build the shell first.**
   Use the sticky near-black header, product mark, text navigation, optional
   session identity, and final GitHub link. Begin useful content immediately
   below the header; do not add a generic marketing hero.
5. **Choose the simplest content composition.**
   Prefer whitespace, hairlines, and clear columns over cards. Use a split
   workbench for input/output tasks, a flat grid or horizontal rail for
   comparisons, and a single reading column for explanatory content.
6. **Implement complete states.**
   Include loading, empty, error, success, disabled, unsupported-capability,
   and long-content behavior where relevant.
7. **Validate the real workflow.**
   Test desktop, intermediate, and mobile layouts; keyboard navigation; visible
   focus; reduced motion; image sizing; and the actual primary task.

## Non-negotiables

- Use system fonts. Do not add a web-font dependency for visual novelty.
- Use near-black actions and focus treatment, not violet or purple.
- Keep corners restrained: generally `2px`, `4px`, or `6px`.
- Use shadows on media, previews, and meaningful interactive surfaces only.
- Use text navigation with an underline. Do not use pill navigation.
- Use semantic HTML, native form controls, and visible labels.
- Preserve a minimum touch target of about `42px`.
- Keep the page usable at `320px` width and 200% zoom.
- Respect `prefers-reduced-motion`.
- Keep all frontend assets and code within the demo folder.
- Reuse wording, components, and layout patterns from existing demos when the
  intent is the same.

## Avoid

- glassmorphism, glow, gradient text, animated gradient backgrounds;
- oversized marketing heroes above the actual demo;
- floating decorative blobs, stars, or abstract AI imagery;
- nested cards or a grid of equally weighted rounded rectangles;
- status pills for information that can be expressed as plain text;
- excessive badges, metadata, labels, and repeated model details;
- purple primary actions;
- hover movement that lifts whole cards;
- monospace used merely to make a page look technical;
- hiding important controls behind icons without text;
- persistent generated content unless the demo explicitly requires it.

## Adapt without breaking consistency

The header, typography, action hierarchy, spacing rhythm, controls, focus
treatment, and responsive principles should remain recognizable across demos.

Adapt:

- product and navigation labels;
- number of navigation destinations;
- main content composition;
- domain-specific status colors and terminology;
- whether authentication controls are present;
- whether the output is imagery, data, text, audio, or diagrams.

When a requirement conflicts with this system, preserve usability and product
truth first, then make the smallest documented visual deviation.

## Completion

Before finishing:

- compare the result with an existing repository demo;
- confirm the primary task is obvious within seconds;
- remove generic scaffolding and redundant containers;
- run the demo's frontend tests;
- inspect the rendered page in a real browser;
- update the demo's `DESIGN.md` when the visual contract materially changes.

In the handoff, state the changed frontend paths and whether the result was
validated locally or deployed. Never deploy unless the user explicitly asks.
