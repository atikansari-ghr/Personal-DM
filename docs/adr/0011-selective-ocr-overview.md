# ADR 0011: Selective OCR, Overview widgets and sign-in designs

Status: accepted (2026-10-06, change sets K and L)

## Context

- Recognising every upload wastes the small server's CPU on pages nobody needs (a 40-page statement for one
  value) and gives the local AI more text than the family wants it to read.
- Families need Arabic and Hindi as well as English, and front and back of a card belong together.
- The start page should show the date in both calendars, the family's public holidays and, optionally, weather.
- Holiday dates change every year, and moon-dependent holidays are only fixed by an official announcement.
- The sign-in page is public, so its design must never leak private pictures or change how people sign in.
- Setup used to create six fixed family accounts that many families do not need.

## Decisions

1. **OCR as explicit jobs with a policy per document type.** Each type is Disabled, Manual or Automatic and lists
   its languages, expected fields and whether AI may read the text. A request names its source files and pages and
   becomes one `ocr_run` job; Automatic processes only the primary OCR source. New installations default to Manual;
   migration `library.0007` keeps existing installations on Automatic with AI allowed, so an upgrade changes nothing
   silently. Removing OCR data never touches the original or confirmed details.
2. **Holidays from the maintained `holidays` library plus administrator overrides** (`HolidayOverride`: confirm,
   rename, add, hide, each with status and source) rather than hard-coded dates. Moon-dependent holidays are marked
   Provisional until confirmed.
3. **Hijri date from `hijridate` (Umm al-Qura)** in the installation timezone, with an administrator adjustment of
   ±2 days for local moon sighting.
4. **Weather through a server-side proxy with a database cache, off by default.** The browser never calls the
   provider; only city coordinates leave the server; one cached forecast serves everyone who chose the same city;
   a failing provider yields a stale or "unavailable" widget, never a broken Overview.
5. **Bundled SVG sign-in art; uploads re-encoded.** Presets ship with the app (no external images). Custom
   wallpapers and logos are decoded, size-checked, re-encoded as WebP with metadata removed and stored under the
   data directory, so they are included in backups. The design is presentation only; authentication methods come
   from the authentication settings.
6. **Setup creates only the Main Administrator**, with an optional step for members. Existing accounts are never
   deleted by migrations, and members are deactivated, not deleted.

## Consequences

- New dependencies (`holidays`, `hijridate`, `python-dateutil`, `six`) and Tesseract language packs
  (`tesseract-ocr-ara`, `tesseract-ocr-hin`); `doctor` reports missing packs and `repair` installs them.
- New installations must run OCR deliberately, which people may not expect; the Text (OCR) tab and the review queue
  make the state visible.
- Holiday accuracy depends on library updates and administrator corrections; the source is always shown.
- Weather needs outbound internet from the server when enabled; it was tested only with a fake local provider.
