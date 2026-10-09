# Themes and layout

## Choose a theme {#choose}

**Settings → My account → Appearance → Theme** shows a preview card for each theme. Click a card to apply it.
**Reset to default** returns to Default Green.

| Theme | Look |
| --- | --- |
| **Default Green** | Clean green and white (the default). |
| **Blue** | Calm, professional blue and white. |
| **Dark** | Dark surfaces, easy on the eyes at night. |
| **Glass Light** | Translucent panels over a soft gradient. |
| **Glass Dark** | Translucent dark panels with depth. |
| **Black & White** | Monochrome, maximum contrast. |

The theme belongs to your account and follows you to every device. Other family members choose their own.

Themes change colours and surfaces only:

- badges, warnings, antivirus and permission states mean the same in every theme;
- status is always shown with text and icons, not colour alone;
- document pages and images are always shown on white, so scans look as they are;
- the browser's address bar and the installed app's title bar follow the theme colour.

### Glass themes {#glass}

Glass blurs only the navigation, the top bar, cards, menus and dialogs. Text areas, tables, form fields, warnings and
the document viewer stay nearly opaque so they remain easy to read. On phones only the navigation layers are blurred,
for speed.

If your browser cannot blur, the glass themes use solid surfaces with the same colours. They also do when your device
asks for *reduced transparency* (macOS/iOS accessibility setting).

### Motion {#motion}

Buttons, cards and dialogs use short transitions (about 0.15 s). If your device asks for *reduced motion*, they are
turned off.

## Layout {#layout}

*Three-panel view* (folder tree, documents, preview) or *Full-page viewer* (documents open on their own page). On
phones the panels stack automatically.

## Resizing panels {#resize}

On wide screens, drag the thin divider between the folder tree and the document list, or between the list and the
preview.

- **Keyboard:** focus a divider (Tab) and use the left/right arrow keys. Home/End jump to the smallest/largest width.
- **Reset:** double-click a divider to go back to the default widths.

Widths are remembered for your account on that device.

## For contributors: design tokens {#tokens}

Every colour, surface, shadow and radius in `frontend/src/styles.css` is a semantic token defined per theme. The
token groups are:

| Group | Tokens |
| --- | --- |
| Surfaces | `--bg`, `--bg-image`, `--surface`, `--surface-2`, `--surface-elevated`, `--side-bg`, `--topbar-bg`, `--btn-bg`, `--input-bg`, `--viewer-bg`, `--overlay` |
| Text | `--ink`, `--ink-soft`, `--heading-strong`, `--muted`, `--line` |
| Brand | `--brand`, `--brand-ink`, `--brand-soft`, `--brand-softer`, `--accent` |
| Status | `--ok-*`, `--warn-*`, `--danger-*`, `--info-*`, `--neutral-*` |
| Shape and focus | `--focus`, `--shadow`, `--shadow-lg`, `--shadow-xl`, `--radius` |
| Motion | `--ease`, `--dur` |
| Glass | `--glass-blur`, `--glass-border`, `--glass-highlight` |

Components never hard-code theme colours. File-type colours, chart series and pictures of other apps (email,
Telegram previews) are the intended exceptions.

`tests/e2e/themes.mjs` checks the presets on the major screens, including:

- contrast measured on the rendered pixels;
- the glass fallback;
- the effect budget on phones;
- focus visibility.

`tests/e2e/a11y.mjs` runs the WCAG audit in every theme. See [ADR 0019](../adr/0019-theme-tokens-glass.md).
