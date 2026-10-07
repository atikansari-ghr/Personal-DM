# ADR 0013: Document types with metadata templates

Status: accepted (2026-10-07, change set N)

## Context

- The Details panel showed **Type** as a hard-coded read-only row and the list of details came from a fixed label
  list in the frontend plus whatever OCR extraction had written. Uploads without a chosen type stayed untyped, so
  documents showed OCR details next to Type "—", and the type could only be set through a hidden dialog.
- Families keep documents the code did not foresee (club cards, school certificates, local permits). Each needs its
  own details, its own expiry field and sometimes its own reminder schedule.
- Folders already express where a document is kept and who can see it. Families organise folders by person, trip or
  year, so a folder is not a reliable statement of what a document is.
- OCR and the local AI produce useful but fallible proposals. Confirmed values drive names and reminders and must
  never be lost or silently replaced.
- Existing installations hold typed and untyped documents with details that must survive the upgrade unchanged.

## Decisions

1. **Types and templates are data, not code.** `DocumentType` rows are seeded once and fully editable by the main
   administrator; each type has a template of `DocumentTypeField` rows (field type, role, required, extraction,
   searchable, validation, order). Field keys are stable so labels can change without touching stored values.
2. **Folder and type are independent.** Moving never changes the type and changing the type never moves the file.
   A folder may carry a *suggested* type for uploads, which is only a suggestion.
3. **Roles instead of fixed keys for dates.** The field with the *expiry* role (and the *issue* / *no expiry* roles)
   is found through the template, so any type can drive expiry dates and reminders. Only confirmed values count.
   Per-type reminder days override the global schedule.
4. **Suggestions never decide.** Folder, OCR and Local AI suggestions for a type are stored with source, reason and
   confidence and shown for Accept / Change / Ignore. Conflicts are shown, not resolved. A confirmed type is never
   replaced by a suggestion; a later different suggestion is recorded only.
5. **Type changes preserve values.** A change is planned first (kept, previous, new, expiry warning) and then applied
   in one place (`doctypes.change_type`), also for bulk changes and for deleting a type with reassignment. Values
   without a field in the new type are kept as *previous details* (scope `unmapped`) for a person to map, keep or
   remove; they do not drive dates. Nothing is deleted implicitly.
6. **Provenance on every value.** Each value records its source (manual, OCR, MRZ, Local AI, import, system,
   migrated), whether a person overrode a machine value, and who confirmed it when. Machine proposals never
   overwrite confirmed values; a differing reading is shown beside it.
7. **One-off details are separate from templates.** A person may add a detail to one document (scope `custom`)
   without changing the type; only the main administrator promotes it into the template, and only that document's
   value moves.
8. **Conservative migration.** The upgrade gives every type a template, marks existing types confirmed with source
   *migrated*, leaves untyped documents untyped (no guessing from field names), keeps values outside the template as
   additional details and adds confirmed issue / expiry / no-expiry fields to the template so reminders keep working.
   A review screen and a report help the administrator classify the rest.

## Consequences

- The administrator can adapt the library to any document kind without a code change, but a badly configured
  template (for example no expiry-role field) means no reminders for that type; the type-change preview and the
  status badge make this visible.
- Type suggestions from text are simple rules (MRZ and keywords); untyped documents may need manual classification
  through the review screen or bulk *Set type…*.
- Previous details can accumulate after many type changes until someone reviews them; the *Needs review* status and
  the report count them.
- Deleting a type in use is refused; documents must be moved to another type first or the type archived. A field
  with stored values can only be turned off.
- Every type operation is audited and recorded in the document history, without OCR text.
