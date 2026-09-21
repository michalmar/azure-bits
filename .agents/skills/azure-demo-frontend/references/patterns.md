# Reusable patterns

Use these as composition patterns, not mandatory components. Keep only patterns
that serve the demo's actual workflow.

## Sticky product header

Use for every interactive demo.

```html
<header class="demo-header">
  <a class="demo-brand" href="/" aria-label="Demo home">
    <span class="demo-brand__family">Microsoft Foundry</span>
    <span class="demo-brand__divider" aria-hidden="true"></span>
    <span>Demo name</span>
  </a>

  <nav class="demo-nav" aria-label="Primary views">
    <button class="demo-nav__item is-active" type="button">Overview</button>
    <button class="demo-nav__item" type="button">Playground</button>
  </nav>

  <div class="demo-header__actions">
    <!-- Optional identity, logout, and GitHub link -->
  </div>
</header>
```

Use no more destinations than the demo needs. If the page has only one view,
omit the navigation rather than inventing tabs.

## Editorial page head

Use a direct outcome-focused heading, one lead, and one support line.

```html
<div class="demo-page-head">
  <div>
    <h1>Compare five image models.</h1>
    <p class="demo-lead">Use the same prompt and inspect the output side by side.</p>
    <p class="demo-support">Default model settings are used.</p>
  </div>
</div>
```

Do not add a kicker, icon tile, or abstract illustration by default.

## Comparison surface

Use for models, generated outputs, service configurations, or architecture
alternatives.

- Keep items aligned to the same grid.
- Give each item the same evidence area.
- Place labels above evidence.
- Use synchronized interaction only when it improves comparison.
- On mobile, use a horizontal snap rail rather than shrinking evidence.
- Put download or inspect actions below evidence as text-first controls.

Do not repeat metadata that is identical across all items.

## Input/output workbench

Use for generators, analyzers, search tools, and transformation demos.

```css
.demo-workbench {
  display: grid;
  grid-template-columns: minmax(340px, 0.62fr) minmax(0, 1.38fr);
  gap: clamp(46px, 6vw, 96px);
}
```

The controls column should be compact. The output column should dominate. Use
whitespace instead of a divider or surrounding card on desktop.

At narrow widths:

```css
.demo-workbench {
  grid-template-columns: 1fr;
}

.demo-workbench__controls {
  padding-bottom: 42px;
  border-bottom: 1px solid var(--hairline);
}
```

## Form group

```html
<label class="demo-field">
  <span class="demo-field__label">Prompt</span>
  <textarea
    class="demo-control demo-control--textarea"
    aria-describedby="prompt-hint"
    placeholder="Describe the subject, composition, light, material, and mood."
  ></textarea>
  <span class="demo-field__hint" id="prompt-hint">
    Include the details that most affect the output.
  </span>
</label>
```

Place validation or capability information close to the relevant field. Avoid
turning short status text into a card.

## Capability statement

Use an indicator, explicit text, and a recovery or next-step hint.

```html
<div class="demo-capability" aria-live="polite">
  <div class="demo-capability__state" data-state="supported">
    <span class="demo-capability__indicator" aria-hidden="true"></span>
    Image input is available.
  </div>
  <p>You can attach one PNG or JPEG.</p>
</div>
```

Supported, unsupported, checking, and error states need distinct text. Color is
supplementary.

## Upload area

An upload interaction may use a light bounded surface because the boundary
communicates the drop target.

Use:

- a subtle-paper background;
- one-pixel dashed border;
- a simple line illustration;
- explicit accepted formats;
- a text button;
- visible disabled and selected states.

Do not create a large decorative upload card if only a file picker is needed.

## Empty output

Before a result exists, reserve the output area with a meaningful placeholder.

The placeholder should:

- prevent layout shift;
- explain where output appears;
- use a low-contrast line illustration or stacked-paper motif;
- become a loading state without changing dimensions;
- avoid fake sample results that users may mistake for actual output.

## Generated result

Show the latest result prominently, then use a flat chronological list for prior
results.

Recommended order:

1. result image or media;
2. concise caption;
3. relevant prompt or source metadata;
4. download action.

Avoid a card grid for session history unless users truly compare history items.

## Error state

State:

1. what failed;
2. what the user can do next;
3. whether their input was preserved.

Use red for the error message, but keep the surrounding surface structurally
consistent. Do not replace the entire page with an alert card.

## Loading state

Keep dimensions stable. Prefer:

- disabled primary action with a verb such as “Generating…”;
- live status text;
- a low-contrast placeholder pulse or background shift;
- preserved prompt and upload.

Do not use a full-screen spinner for a local operation.

## Session reset

If a demo has browser-session-only content, expose “Start new session” or
“Clear session” as a secondary destructive action. Explain exactly what will be
discarded. Require confirmation only when losing the current work would be
surprising or costly.

## Small-screen header

At narrow widths:

- keep the product name and actions on the first row;
- move primary navigation to the second row;
- hide the family label before hiding the demo name;
- preserve text labels for logout and important actions;
- do not collapse two navigation items into a hamburger menu.
