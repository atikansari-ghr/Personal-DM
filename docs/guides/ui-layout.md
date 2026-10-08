<!-- audience: maintainer -->
# UI layout rules (for contributors)

These rules came out of Change Set R (UI alignment and responsive layout). They keep text, icons, badges and actions
aligned on every screen without per-page pixel nudges. `tests/e2e/layout.mjs` checks them automatically on 27
screens at seven viewport sizes.

## The rule behind most alignment bugs {#flex-basis}

A flexible item in a **wrapping** flex row must have a real minimum basis.

`flex: 1` means `flex-basis: 0`. A row only wraps when the *basis* sizes of its items no longer fit. So a title
with basis 0 next to four buttons never makes the buttons wrap: the buttons keep their full width and the title is
squeezed into whatever is left, often one word per line. That was the root cause of the document preview defect:
in a 746 px pane the title got 192 px.

Use the shared primitives instead of fixing single pages:

| Primitive | Use |
| --- | --- |
| `.row > .grow`, `.list-item > .grow` | Header rows (title + actions) and list rows (icon + text + badges or buttons). The growing item has a basis of 12 rem (`--grow-basis`), so actions wrap onto their own line before the text gets narrow. |
| `.doc-header`, `.doc-header-main`, `.doc-actions` | The document header in the preview pane and on the full page. |
| `.doc-badges` | A group of status badges (OCR, antivirus, expiry, archived) that stays together and wraps as a group. |
| `.doc-meta` | Inline metadata such as "file · size · version". Short items never break; the separator belongs to the item before it, so a wrapped line never starts with "·". Long file names wrap anywhere (`overflow-wrap: anywhere`). |
| `.tabs-aside` | A note at the end of a tab bar; keeps its words together. |
| `min-width: 0` | On any flex or grid child that contains text, so it may shrink instead of overflowing. |

## Size by the space a component has, not the window {#containers}

The preview pane (`.detail-pane`), the full document page (`.doc-page`) and the viewer (`.viewer`) are CSS **size
containers**. Their layout depends on their own width, because a narrow pane on a wide screen and a phone need the
same treatment:

- In panels narrower than 60 rem, document actions get their own row under the title, badges and file details.
- Below 34 rem, *Share* and *Open full page* become icon buttons. They keep their accessible names (`aria-label`
  and `title`); *Download* keeps its label.
- Below 34 rem, the viewer toolbar is one row that scrolls sideways instead of several ragged rows.

## Responsive modes {#responsive}

| Width | Folders screen |
| --- | --- |
| ≥ 1280 px | Three panels: folder tree, document list, preview. List and preview share the space equally (resizable). |
| 761–1279 px | Folder tree + document list; an open document takes the whole width, with **← Back to folder**. |
| ≤ 760 px | One panel at a time: Folders → Documents → Preview. The sidebar becomes a menu. |

Settings rows switch to a single column whenever a row is narrower than two 16 rem columns.

## Long text {#long-text}

- Headings: wrap normally; very long words break (`overflow-wrap: break-word` on h1–h4).
- File names: wrap anywhere inside the name, never word by word in a squeezed column.
- Lists and tables: a table that is wider than the page scrolls sideways (help tables keep 9 rem columns). Never hide
  security, expiry or error meaning behind truncation.
- Arabic and other right-to-left document metadata renders inside the left-to-right application without breaking the
  layout. The app itself is not mirrored.

## Do not {#dont}

- Add negative margins, absolute positioning or pixel nudges to move text into place.
- Measure text in JavaScript to correct normal CSS layout.
- Hide overflow to conceal broken content, or shrink fonts until a defect is less visible.

## Checking a change {#check}

`scripts/e2e.sh` runs `tests/e2e/layout.mjs` after the other browser tests. For each screen and viewport it reports:

- horizontal overflow;
- squeezed text and wrapped button labels;
- misaligned icons;
- overlapping or off-screen controls;
- unnamed icon-only controls.

It also checks the document header with five synthetic file names (short, normal, long, very long without spaces,
Arabic), plus menus and dialogs inside the viewport and visible keyboard focus.

The geometry of the document header is compared with `tests/e2e/layout-baseline.json` (x and width ±6 px, y and height ±24 px because fonts differ between machines). After an
intentional layout change, run with `UPDATE_BASELINE=1` and review the JSON diff in the pull request; never accept a
new baseline without looking at the screenshots in `tests/e2e/out/layout/` (uploaded by CI as an artifact).
