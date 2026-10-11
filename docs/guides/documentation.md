<!-- audience: maintainer -->
<!-- reviewed: 2026-10-11 -->
# Writing and checking the documentation (for contributors)

The guides in `docs/guides/` are part of the product. The app shows them under **Help & documentation**, with
categories, search, breadcrumbs, a table of contents and screenshots. GitHub shows them as normal Markdown. Update a
guide in the same change as the screen or behaviour it describes. A stale guide or screenshot is a bug.

## Structure of a guide {#structure}

1. `<!-- audience: admin -->` (or `maintainer`) when the guide is not for everyone, and `<!-- reviewed: YYYY-MM-DD -->`.
2. A short introduction: what the feature does and who can use it.
3. **Prerequisites**, then **numbered steps** that use the exact labels on the screen (buttons in **bold**).
4. A screenshot right after the step it shows.
5. An **expected result** callout.
6. **Troubleshooting** (symptom, cause and fix), and rollback where it applies.

Every section has a stable anchor (`## Heading {#anchor}`). Settings help keys and **Learn more** links point to these
anchors, so do not rename them.

## Callouts {#callouts}

Use GitHub's alert syntax. It renders on GitHub and as coloured callouts in the app.

| Write | Shown as |
| --- | --- |
| `> [!NOTE]` | Info |
| `> [!TIP]` | Tip |
| `> [!IMPORTANT]` + `> **Expected result:** …` | Expected result |
| `> [!WARNING]` | Warning |
| `> [!CAUTION]` | Critical |
| `> [!WARNING]` + `> **Experimental.** …` | Experimental |
| `> [!NOTE]` + `> **Privacy** …` | Privacy |

## Screenshots {#screenshots}

Screenshots are real captures of the application with synthetic demo data, made by the browser tests. See
[Public screenshots](screenshots.md) for:

- sizes and the device pixel ratio;
- the quality and privacy gates;
- how to refresh the images.

Reference them with a relative path and a meaningful alt text:

```
![Recovery Explorer with the restore-point timeline, folders and documents](../images/screenshots/recovery-explorer.png)
```

Never show:

- real family documents, names, addresses, email addresses or phone numbers;
- secrets, Recovery Keys, tokens, webhook addresses or WhatsApp QR codes or session data;
- real public IP addresses, a real private network layout or production backup locations.

## Automated checks {#checks}

`python3 scripts/check_docs.py` runs in `scripts/verify.sh`, in CI and in the backend test suite. It fails on:

- links to missing files or anchors, including the Learn more links in the frontend and the settings help keys;
- referenced images that do not exist, and images without alt text;
- screenshots that no document uses (orphans);
- outdated UI terms;
- missing `reviewed` dates on the Backup & Recovery, notification and security guides;
- critical flows with too few screenshots.

`tests/e2e/recovery.mjs` also opens Help in a browser and checks:

- categories, breadcrumbs, the table of contents and callouts are shown;
- every screenshot loads;
- every Learn more link on the Backup & Recovery page resolves.
