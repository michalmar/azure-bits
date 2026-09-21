# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Solution architects, developers, customers, and stakeholders evaluating Microsoft
Foundry image models during a live demonstration or technical workshop.

## Product Purpose

Provide a small, deployment-ready demo that makes image-model differences easy to
see and lets users safely try their own prompts. Success means a presenter can compare
all five deployed models with the same inputs, then let an audience member generate and
download an image without leaving durable user content behind.

## Positioning

The demo combines a proof-sheet comparison gallery with a session-scoped playground.
It emphasizes side-by-side evidence from identical prompts rather than presenting one
model result in isolation.

## Operating Context

- Runs locally with the developer's Azure CLI identity and in Azure Container Apps
  Express with a user-assigned managed identity.
- Uses the Microsoft Foundry project supplied through local environment or
  deployment configuration.
- Calls these existing deployments:
  `gpt-image-2.5-sunburst`, `MAI-Image-2.6-Flash`, `MAI-Image-2.6`,
  `MAI-Image-2.5`, and `gpt-image-2`.
- The gallery contains three fixed prompts and one output from every model for each
  prompt, for 15 comparison images total.

## Capabilities and Constraints

- Generate from a prompt using a selected model's default settings.
- Accept an uploaded image plus a prompt only when the selected model's API confirms
  image-input support.
- Keep generated images only for the active browser session; do not use databases,
  Blob Storage, durable volumes, or server-side history.
- Let users download generated images.
- Starting a new session clears all browser-held prompts, uploads, and generated
  images.
- Use managed identity and Azure RBAC in Azure; never use API keys, storage keys,
  client secrets, or credentials in frontend assets.
- Deploy with Terraform to Azure Container Apps Express in Sweden Central, scaling
  from zero to at most one replica.
- Keep the implementation focused, understandable, responsive, and accessible.

## Brand Commitments

- Customer-ready Microsoft Azure and Foundry context without imitating the Azure
  portal.
- Plain, active language and a modern interface that stays simple while making
  model comparison engaging.

## Evidence on Hand

- Five model deployments already exist in the configured Foundry project.
- No approved benchmark claims, customer logos, testimonials, or model-quality
  rankings are available and must not be invented.
- Gallery outputs are synthetic demonstrations and should be labeled as such.

## Product Principles

1. Compare identical inputs before judging model differences.
2. Make capability and failure states explicit rather than silently degrading.
3. Keep user-created media ephemeral and under the user's control.
4. Prefer a clear live demonstration over a feature-heavy application.
5. Use secure, passwordless Azure access with least-privilege roles.

## Accessibility & Inclusion

Support keyboard operation, visible focus, meaningful status announcements, useful
image alternative text, touch-friendly controls, reduced motion, and WCAG 2.2 AA
contrast for the primary experience.
