# Frontend validation

Use the smallest available checks that prove the current change.

## Visual checks

Inspect the rendered page at:

- a wide desktop viewport;
- an intermediate viewport near the layout breakpoint;
- a narrow mobile viewport near `375px`;
- `320px` width when practical;
- 200% browser zoom.

Confirm:

- the near-black header is distinct from the white canvas;
- the primary task is visible without scrolling through a marketing hero;
- output or evidence receives more space than controls;
- controls align optically;
- no text or control overflows;
- images have stable dimensions;
- shadows are restrained and consistent;
- rounded rectangles do not become page scaffolding.

## Interaction checks

Exercise:

- every primary navigation destination;
- keyboard focus order;
- active navigation and tab state;
- the complete primary task;
- disabled controls;
- loading behavior;
- error recovery;
- empty and success states;
- file selection and removal when present;
- downloads when present;
- session reset when present.

## Accessibility checks

- All controls have accessible names.
- Form labels remain visible.
- Focus is visible on white and dark surfaces.
- Text and controls meet WCAG 2.2 AA contrast.
- Status changes use a live region when asynchronous.
- Custom tabs use the correct role and selection state.
- Keyboard users can reach every action.
- Reduced-motion mode does not hide content or leave long animations running.
- Information is not conveyed by color alone.

## Technical checks

- Run the demo's targeted frontend tests.
- Check the browser console for errors.
- Verify no unexpected horizontal page overflow.
- Verify media paths and downloads.
- Verify JavaScript is enhancement rather than the only source of essential
  explanatory content where practical.
- Confirm no credentials, tokens, or private identifiers appear in frontend
  assets.
- Confirm all demo assets live inside the demo folder.

## Design-system checks

- Uses the canonical token roles or documents a necessary deviation.
- Uses the standard header and navigation relationship.
- Uses system typography.
- Uses near-black primary actions.
- Uses cyan sparingly.
- Avoids gradients, glass, glow, pill navigation, decorative AI imagery, and
  nested cards.
- Updates the demo's `DESIGN.md` when a durable visual decision changes.

## Handoff

Report:

- changed frontend paths;
- the principal visual or UX change;
- tests or browser checks performed;
- whether the result is local only or deployed;
- any intentional deviation from the shared design system.
