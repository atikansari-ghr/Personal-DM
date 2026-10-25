# Overview

The Overview is your start page. It only shows documents you are allowed to see. What it shows, in which order, size and style, belongs to your account, so your phone, tablet and computer show the same Overview.

## Widgets {#widgets}

| Widget | What it shows |
| --- | --- |
| Today | Today's Gregorian date and the Hijri date (see below) |
| Weather | Current conditions and a five-day forecast for the city you choose (when the administrator enabled weather) |
| Documents summary | Documents, expiring soon, expired, needs review, shared with you and storage used; each tile opens the matching list |
| Month calendar | The month with holiday markers; previous / next month and **Today**; select a day for its holidays |
| Upcoming holidays | The next public holidays of the chosen countries, with the country flag and how many days away |
| Expiring soon | Documents that expire in the next 90 days |
| Shared with me | The latest documents owned by others that you may open |
| Recent documents, Recent activity | What was added or changed lately |
| Review queue, Backup status, Family library, Saved views and single counters | As before; backup status is for administrators only |

New accounts start with the suggested widgets: Today, Weather, Documents summary, Month calendar, Upcoming holidays, Expiring soon, Shared with me, Recent documents and Recent activity. Accounts that had already chosen their widgets before an upgrade keep their choice; add the new widgets with **Customize Overview**.

## Customize Overview {#customize}

Choose **Edit Layout** to change your Overview. Outside Edit Layout nothing moves or resizes by accident. Your layout
is **yours alone**: it is saved on the server for your account (not only in the browser), follows you to every
device, and never changes anyone else's Overview.

### Edit Layout {#edit-layout}

- **Add widget…** adds a tile that is not shown (to the General group); **×** removes one.
- **Move** a tile by dragging it (onto another tile, or onto a group), or with the **‹ / ›** buttons and the tile's
  **Group** list (keyboard, screen readers and touch).
- **Resize** freely with the **corner handle**: drag it to change the width (12 columns on a desktop) and the height
  (rows of 90 px). The **− / +** buttons change the width one column at a time and the **Height** list sets the height
  (*fit content* or a number of rows). Every tile has a minimum and maximum size, so it stays readable; tiles never
  overlap — the grid places them in order and reflows the rest.
- **Style**: *Rectangular* (default), *Compact rectangular*, *Circular* or *Compact circular*. Circles are offered only for single-value widgets (Today, Weather and the counters); calendars, lists and tables stay rectangular so they remain readable.
- **⚙ Widget settings**: show or hide the Hijri date and its Arabic month name; choose countries for the calendar and holidays; the number of items in lists.
- **Save layout** or **Cancel**. Nothing changes until you save.

On a tablet the Overview uses two columns and on a phone (and in the installed app) one; tiles keep their groups and
order and a fixed height becomes "fit content". This is only how the page is shown: your desktop sizes are not
changed by opening the Overview on a phone.

### Groups {#groups}

Create your own groups — for example *Family*, *Documents*, *Renewals*, *Travel* or *Security* — with **Add group**.
In Edit Layout you can rename a group, move it up or down, collapse or expand it, and move tiles in and out. A
collapsed group stays collapsed on all your devices (you can collapse and expand outside Edit Layout too).

**General** is the default group and cannot be removed. **Removing a group never removes its tiles**: when it still
has tiles you choose the group they move to (General by default). Group names have 1 to 40 characters.

### Reset Layout {#reset-layout}

**Reset Layout** (in Edit Layout, after a confirmation) puts *your* Overview back to the default tiles, sizes and
groups. It changes nothing else: no document, no setting and no other person's layout.

The order and widget selection can also be changed in Settings → My account → Appearance → Overview widgets. Tiles
added to Personal DM in a later release appear in your General group; tiles you removed stay removed.

## Hijri date {#hijri}

The Hijri date is calculated with the open-source *hijridate* library, which implements the **Umm al-Qura** calendar used in Saudi Arabia (valid for 1343–1500 AH, that is 1924–2077). "Today" follows the **installation timezone** (Settings → General), not the browser, so everyone sees the same date. Because a local moon sighting can differ from the calculated calendar, the administrator can shift the Hijri date by up to two days (Settings → Overview & sign-in → *Hijri date adjustment*).

## Holidays {#holidays}

Public holidays come from the bundled open-source **holidays** library; no dates are hard-coded. Saudi Arabia and India are selected by default. The administrator adds or removes countries in **Settings → Overview & sign-in → Holiday countries** with a searchable list of the supported countries (up to 12).

Each holiday shows its source and status:

- **Confirmed** — a fixed date from the library (for example Saudi National Day or Indian Republic Day), or a date the administrator confirmed.
- **Provisional** — a calculated date for a holiday that depends on the moon (Eid al-Fitr, Eid al-Adha, Day of Arafah, Islamic New Year, Prophet's Birthday and similar). It can move by a day after the official announcement.

Administrators correct the data under **Holiday corrections**: confirm or rename a provisional date, add a holiday the library lacks, or hide a library holiday on a date. Every correction records a status and a source (for example "official announcement"). Corrections never change the library or the country list; deleting a correction restores the library's data.

## Weather {#weather}

Weather is **off by default**. An administrator enables it in **Settings → Overview & sign-in**:

- **Weather provider**: Open-Meteo, which needs no account. The forecast and city-search addresses can be changed for a commercial plan or a self-hosted mirror; an optional **API key** is stored encrypted and never shown again.
- **Weather cache** (default 30 minutes): forecasts are reused for everyone who chose the same city, so the provider is asked rarely.
- **Temperature units** and a **default city** for people who have not chosen their own.
- **Test connection** checks city search and one forecast with the saved settings.

Each person chooses their own city in the widget (**Choose your city** / the city button). Only the city's coordinates are sent to the provider — never names, documents or account details.

If the provider cannot be reached, the widget shows the last forecast (up to 24 hours old) marked *not current*, or "Weather unavailable" with **Try again**. The rest of the Overview always loads.
