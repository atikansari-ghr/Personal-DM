# ADR 0017: Shared layout primitives, container-based responsiveness and a layout audit

Status: accepted (2026-10-08, change set R). The change prompt called it "Change Set Q" with AT-211…AT-225; those
numbers were already used by the PaddleOCR change set, so it is Change Set R with AT-231…AT-245 here
(prompt AT-n = AT-(n+20)).

## Context

A production screenshot of the Folders preview showed the document title wrapping word by word, with the OCR badge
and the antivirus shield detached and the "file · size · version" line breaking item by item, while the pane had
plenty of free width. Reproduced with synthetic documents at 1920×1080, the preview pane was 746 px wide but the
title got 192 px.

**Root cause.** The header was a wrapping flex row (`.row.between`, `flex-wrap: wrap`) containing:

- the title block `.grow` = `flex: 1`, i.e. `flex-basis: 0`;
- an actions row of four non-wrapping buttons, about 520 px.

A flex row decides whether to wrap from the items' *basis* sizes. With a basis of 0 the title never forces a wrap,
so the buttons kept their full width and the title got the remainder. Narrower windows happened to wrap differently,
which is why the defect looked random.

The same pattern (`row between` + `grow` beside fixed-width controls) appears in about 26 places. The audit found
the same squeeze in five other places:

- the document list cards (name and details squeezed beside the status badges, 61 px columns at 1366 px);
- the tab-bar note "No details yet";
- the Overview date widget;
- the settings label column on tablets;
- the help tables.

A second cause: responsive rules were keyed to the **window** width. A narrow preview pane on a wide screen (or a
tablet showing the folder tree next to an open document, 273 px) therefore got the desktop layout.

## Decision

1. **Fix the primitive, not the page.**
   - `.row > .grow` and `.list-item > .grow` now have a real basis (`--grow-basis`, 12 rem), and list rows may wrap, so actions and badges wrap before text is squeezed.
   - New shared components: `.doc-header` / `.doc-header-main` / `.doc-actions`, `.doc-badges` (status badges as
     one group), `.doc-meta` (inline metadata whose separators stay with the preceding item; long file names wrap
     anywhere) and `.tabs-aside`.
   - Headings get `overflow-wrap: break-word`.
2. **Container queries for components that live in panes.**
   - `.detail-pane`, `.doc-page` and `.viewer` are size containers.
   - Below 60 rem the document actions take their own row.
   - Below 34 rem *Share* and *Open full page* become icon buttons with accessible names, and the viewer toolbar
     becomes a single row that scrolls sideways.
3. **Responsive modes.**
   - Three panels only from 1280 px (sidebar 260 px + three usable panes). Below that an open document takes the
     whole browser width, with *Back to folder*.
   - List and preview share the width equally.
   - Settings rows switch to one column whenever two 16 rem columns don't fit.
   - Help tables keep 9 rem columns and scroll sideways.
4. **Status is never an icon or colour alone in the header.** The antivirus state is shown as a labelled badge
   ("Clean", "Not scanned", …) inside the badge group.
5. **Automated layout audit** (`tests/e2e/layout.mjs`, run by `scripts/e2e.sh` and CI):
   - Covers 27 screens × 7 viewports: 1920×1080, 1440×900, 1366×768, tablet landscape and portrait, 430 and 390 px
     phones.
   - Checks overflow, squeezed text, wrapped buttons, icon/label misalignment, overlapping and off-screen controls,
     and unnamed icon-only controls.
   - On the document screen it also checks the header with five synthetic names (including very long and Arabic),
     menus and dialogs inside the viewport, and visible focus.
   - The document-header geometry is compared with a reviewed JSON baseline (x/width ±6 px, y/height ±24 px) instead of pixel
     snapshots, which differ between machines because of fonts. Screenshots for human review are a CI artifact.

## Consequences

- On 1280 px windows the document actions sit under the title, and the full-page view keeps them beside the title
  only when there is room.
- Between 1100 and 1279 px an open document hides the folder tree (back button) instead of squeezing three panes.
- Run the layout audit before UI changes. `UPDATE_BASELINE=1` regenerates the geometry baseline, and its diff must be
  reviewed.
- Container queries need current browsers (Chrome/Edge 105+, Safari 16+, Firefox 110+), which the app already
  requires for passkeys and the PWA.
