# ADR 0022: Trusted Zones, sign-in map privacy and explainable risk

Status: accepted (2026-10-11, change set T).

## Context

Sign-ins from the home network showed "Unknown country", because private addresses have no GeoIP entry. People wanted:

- to see where their sign-ins came from;
- to recognise their own devices;
- to react to a device they do not recognise.

All of this had to work without sending addresses to third parties, and without GeoIP mistakes locking people out.

## Decision

1. **Location is resolved in this order:**
   - a **Trusted Zone**: several IPv4/IPv6 CIDRs per zone, and the longest prefix wins;
   - a private or local network;
   - the server's local GeoIP database (MaxMind format).

   Only a City database gives approximate coordinates. A Country database gives a country-level point (a dashed circle
   on the map). A zone's map pin is entered by the administrator and always labelled *configured Trusted Zone
   location*.
2. **Privacy.**
   - Addresses are never sent to an external geolocation service or to the tile server.
   - Leaflet is bundled. The browser fetches only ordinary map tiles from the configured tile URL. The CSP `img-src`
     adds that origin dynamically.
   - Routine notifications show an approximate location and network. Trusted Zone addresses are shortened, and full
     addresses appear only in the app.
3. **Scope.** People see their own sign-ins. A delegate with the *membership* scope sees their group. The main
   administrator sees everyone. This is enforced server-side.
4. **Risk:**
   - levels are Normal, Low, Warning and High;
   - each level comes with the reasons behind it: zone, recognised device, sign-in method, new country, and impossible
     travel (faster than 900 km/h, only with City-level or zone coordinates);
   - High notifies the person and the administrators;
   - risk **never blocks** a sign-in. Country blocking stays a separate, deliberate policy.
5. **Recognised devices.**
   - Each device carries a random, long-lived HttpOnly cookie (`pd_device`). Only its SHA-256 hash is stored.
   - **Mark Unrecognized** ends that device's sessions, removes the recognition (sessions bound to the device are
     rejected from then on), audits the action, notifies the person, and suggests next steps without performing them.
6. **Retention:** sign-in records and device history follow the login audit retention (1 year by default). Devices
   with an active session are kept.

## Consequences

- GeoIP is approximate. The UI and the guide say so, and nothing automatic depends on it alone.
- A cleared browser counts as a new device. That is the safe direction.
