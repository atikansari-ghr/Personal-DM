# ADR 0019: Semantic theme tokens, Dark and Glass presets

Status: accepted (2026-10-09, change set S).

## Context

There were three themes (green, blue, mono) that only swapped five brand colours. 165 colour literals were scattered
through `styles.css`: `background: #fff` on buttons, cards, menus, dialogs, viewer and tables, plus fixed status
colours. So a dark or translucent theme would have left white islands. `tests/e2e/themes.mjs` now counts components that
stay white in the dark themes and fails if there are any.

## Decision

1. **One token vocabulary** (`docs/guides/themes.md#tokens`):
   - surfaces, text, lines, brand, status, overlay, viewer, focus, shadows, radius, motion and glass.
   - Every theme defines the full set: light themes share the base block, dark themes the dark block, and the glass
     themes override surfaces.
   - Components use tokens only. A preview element can render any theme by carrying its own `data-theme`, which is how
     the theme gallery works.
2. **Presets:** Default Green (unchanged default), Blue, Dark, Glass Light, Glass Dark. Black & White is kept, so no
   existing preference breaks.
3. **Glass, selectively:**
   - Blur is applied only on the navigation, top bar, cards, menus and dialogs, and never nested.
   - Content areas (tables, viewer, alerts, text) use nearly opaque `--surface-2`.
   - Fallback when `backdrop-filter` is unsupported or `prefers-reduced-transparency: reduce`: solid surfaces.
   - Phones: only the navigation layers are blurred.
   - The gradient sits on a fixed pseudo-element (no `background-attachment: fixed`).
4. **Motion:** short transitions (140 ms) on interactive surfaces, dialog/menu entrance, all disabled under
   `prefers-reduced-motion`.
5. **Unchanged meaning:** status keeps text and icons; document pages and images stay on white in every theme. The
   browser `theme-color` follows the theme.

## Consequences

- New UI must use tokens. The theme e2e test fails if a component stays white in a dark theme on the audited screens.
- Contrast is verified on rendered pixels (`themes.mjs`) and with axe-core in all six themes (`a11y.mjs`).
