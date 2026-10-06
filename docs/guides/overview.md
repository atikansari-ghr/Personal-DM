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

Choose **Customize Overview** to enter edit mode:

- **Add widget…** adds a widget that is not shown; **×** removes one.
- **Reorder** by dragging a widget, or with the **‹ / ›** buttons (keyboard, screen readers and touch).
- **Resize** with **− / +**. Each widget has a minimum and maximum width on a four-column grid, so widgets never overlap or run off the screen. Tablets use two columns and phones one, keeping the order.
- **Style**: *Rectangular* (default), *Compact rectangular*, *Circular* or *Compact circular*. Circles are offered only for single-value widgets (Today, Weather and the counters); calendars, lists and tables stay rectangular so they remain readable.
- **⚙ Widget settings**: show or hide the Hijri date and its Arabic month name; choose countries for the calendar and holidays; the number of items in lists.
- **Reset to default**, **Cancel** or **Save layout**. Nothing changes until you save.

The order and widget selection can also be changed in Settings → My account → Appearance → Overview widgets.

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
