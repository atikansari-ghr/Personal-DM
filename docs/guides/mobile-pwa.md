# Phone and tablet (PWA)

## Install the app {#install}

The web app can be installed like an app (it needs HTTPS):

- **Android (Chrome):** menu ⋮ → *Install app* / *Add to Home screen*.
- **iPhone/iPad (Safari):** Share → *Add to Home Screen*.
- **Desktop (Chrome/Edge):** the install icon in the address bar.

The installed app is called **Personal DM** and uses the green document-and-shield icon.

### iPhone/iPad: the icon shows a letter instead of the app icon {#ios-icon}

iOS takes the Home Screen icon once, when the shortcut is created, and never updates it. If an earlier shortcut shows a
letter (for example "A"), do a fresh install:

1. Long-press the old shortcut → **Remove App** → **Delete from Home Screen**.
2. Open the address in **Safari** (not an in-app browser), wait for the sign-in page.
3. Share → **Add to Home Screen**. The preview at the top must show the green icon and the name *Personal DM*; if it
   shows a letter, stop and check the next point.
4. Tap **Add**, open the app from the Home Screen and check it opens full screen (no Safari address bar).

If the preview still shows a letter, iOS could not load the icon without your session. On the server, run
`sudo personaldocs check-access`. Step 5 checks `/apple-touch-icon.png`, `/manifest.webmanifest`, `/icon-192.png`,
`/icon-maskable-512.png` and `/favicon.ico` from outside, without signing in. A reverse proxy that puts a sign-in page
in front of everything (Pangolin with authentication, authentik forward auth) must let these files through
unauthenticated: they contain no personal data.

Android and desktop Chrome/Edge read the icons from the manifest and update them on their own after a while; reinstall
to see a new icon at once.

### Icon files {#icons}

All icons are generated from one master drawing, `frontend/public/icon.svg`, by `node scripts/make_icons.mjs`:

| File | Size | Used by |
| --- | --- | --- |
| `icon-512.png`, `icon-192.png` | 512, 192 | manifest, purpose *any* (rounded) |
| `icon-maskable-512.png`, `icon-maskable-192.png` | 512, 192 | manifest, purpose *maskable* (full bleed, artwork in the 80 % safe zone) |
| `apple-touch-icon.png` (+ `-precomposed`) | 180 | iPhone/iPad Home Screen (opaque; iOS rounds the corners) |
| `favicon.ico` (16/32/48), `favicon-32.png`, `favicon-16.png`, `icon.svg` | — | browser tabs |

A missing icon path answers 404, never the app page. In the past `/apple-touch-icon.png` was answered with the app's
HTML, which iOS cannot use.

## Upload from your phone {#upload}

In **Upload**, choose *Choose files* (Files or Photos) or *Take photo* to use the camera. There is no built-in scanner or cropping; use your phone's scanner app for multi-page scans and upload the PDF.

## Share into the app {#share-in}

On Android, an installed app may appear in the system share sheet: share a PDF or photo to *Personal DM* and choose the folder. iPhones do not support sharing files into web apps — use Upload instead.

## Share out of the app {#share-out}

Open a document → **Share → Share file…** to use your device's share menu where supported. Otherwise download the file and share it from your device. A shared copy is independent of the app.

## Same features on phone, tablet and computer {#parity}

Every function works on phones and tablets; only the layout changes:
- **Folders:** Folders → Documents → Preview, one screen at a time. **☰** shows the folder tree; **← Back to folder**
  returns to the list.
- **Moving:** drag and drop is for computers; on touch screens use the ⋮ menu → **Move to…** (it does the same
  thing with the same checks). See [moving](getting-started.md#moving).
- **Viewer:** the zoom/fit toolbar is one row you can swipe sideways; pinch-zoom of the page also works, but the
  buttons are always there. See [viewing documents](getting-started.md#viewer).
- **Tables** (notification choices, family members, login audit) turn into stacked rows on narrow screens.
- **Settings follow your account:** theme, Overview widgets with their order, sizes and styles, layout, notification choices and
  profile photo are stored on the server, so a change on your computer appears on your phone (open the app again or
  switch back to it). Only device-specific things stay on the device: panel widths, list/grid view and offline copies
  (offline copies are chosen per device, see [offline access](offline-export.md)).

Each release is checked automatically at tablet, phone portrait and phone landscape sizes (no sideways scrolling of
the page, controls large enough to tap, every screen loads). Real-device behaviour still differs between platforms
and browser versions; see the test report for what was verified on real devices.
