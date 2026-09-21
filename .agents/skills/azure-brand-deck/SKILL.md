---
name: azure-brand-deck
description: Create Microsoft Azure brand-styled PowerPoint presentations (customer briefings, partner decks, internal Azure/M365 product narratives). Use when the user asks for "Azure-styled", "Microsoft branded", "customer briefing deck", or wants a presentation that matches the official Microsoft Azure PowerPoint template look (deep blue + purple + cyan palette, Segoe UI, wireframe sphere motif, 4-color Microsoft logo).
---

# Azure Brand Deck Skill

Builds polished, customer-ready slides in the official Microsoft Azure visual language. Use this in combination with the standard `pptx` skill: this skill provides the **brand layer** (palette, typography, motif assets, reusable slide patterns); `pptx` provides the generation + QA pipeline.

## When to invoke

Trigger when the user wants:
- A Microsoft Azure or Microsoft 365 customer briefing deck
- A presentation styled like the Microsoft Azure PowerPoint Template
- Slides for Azure AI Foundry, Microsoft Fabric, Agent Framework, Entra, Copilot, or any Azure cloud-native story
- A "branded", "Microsoft-looking", or "customer-ready" deck about a Microsoft product

## Workflow

1. **Read the brand reference** — `palette.md` (colors, fonts, typography) and `patterns.md` (copy-paste slide layouts).
2. **Generate brand assets once per session** — from the workspace root, run `python3 .agents/skills/azure-brand-deck/make_assets.py` (requires `cairosvg`; writes Microsoft logo, wireframe sphere, capsule chain motif PNGs into `working/assets/`).
3. **Author the deck** in a `working/create-presentation.js` file using pptxgenjs and the patterns from `patterns.md`.
4. **Hand off to the `pptx` skill** for the generation + visual QA loop. The `pptx` skill renders the file and inspects each slide image for overflow, alignment, and contrast issues.
5. **Output** lands at `output/<name>.pptx`.

The `pptx` skill is mandatory for the build step — never skip its visual QA pass, especially for non-English versions where text can be 30–50% longer.

## Key design rules

- **Sandwich structure**: dark Azure-blue cover and dark divider slides bracket light-background content slides
- **Segoe UI everywhere** — Light for large display type, Regular for body, Semibold for emphasis (no Arial)
- **Microsoft logo top-left** on every slide, white variant on dark backgrounds
- **Footer band** with two-digit slide number in azure blue + section title in muted grey, separated by a thin rule
- **Card-and-accent pattern** — light-grey card (`F4F4F8`) with a coloured accent strip (left edge or top edge) using one of the six brand colours
- **Wireframe sphere + capsule chain** decorate cover, section dividers, and the thank-you slide at low transparency
- **No accent lines under titles** — they look AI-generated; rely on whitespace and the section-tag-above-title pattern instead

## Files

- `palette.md` — full colour palette, font stack, typography scale, contrast rules
- `patterns.md` — copy-paste pptxgenjs snippets for title slide, content slides, section divider, agent/feature roster, architecture matrix, thank-you slide
- `make_assets.py` — generates the Microsoft 4-colour logo (regular + white), wireframe sphere (three colourways), and Azure capsule-chain motif PNGs

## Localization

Technical terms stay in English even when the surrounding narrative is translated — product names (Microsoft Agent Framework, Azure AI Foundry, Microsoft Fabric, Entra ID), service names, identifiers, and architectural concept labels (Agent / Tool / Orchestration). Translate only the narrative, section headings, step verbs, and takeaway prose.
