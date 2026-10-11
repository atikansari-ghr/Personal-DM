<!-- reviewed: 2026-10-11 -->
# Sign-in security, Trusted Zones and the sign-in map

Personal DM records where each sign-in came from, which device was used, and how unusual it looks. It also lets you
end sessions or distrust a device.

## Trusted Zones {#trusted-zones}

A **Trusted Zone** gives a friendly name to your own networks. With a zone such as *Home*, sign-ins from your home
network show **Home** instead of a misleading "Unknown country".

**Set up a zone (main administrator):**

1. Open **Settings → Activity & health → Sign-in map & Trusted Zones**.
2. Click **Add zone**.
3. **Friendly name:** for example `Home`, `VPN` or `Office`.
4. **Networks:** one CIDR per line. IPv4 and IPv6 can be mixed, for example `192.168.2.0/24`, `192.168.20.0/24`
   (a second VLAN) and `fd00:1::/64`.
5. **Type:** Home, VPN, Office, Family or Other.
6. Optional: a **map pin** (see below).
7. Click **Save**.
8. Use **Test an address** to check which zone an address belongs to. The address is not sent anywhere.

![Trusted Zones with several networks, a map pin and the address test](../images/screenshots/security-trusted-zones.png)

Rules:

- When networks overlap, the most specific one wins. A `/24` inside a `/16` belongs to the `/24`'s zone. This is
  deterministic.
- A Trusted Zone is **one** risk signal. A sign-in from Home is not automatically safe.

### Map pin {#pins}

A pin places the zone on the map. Enter latitude and longitude in decimal degrees; an approximate point is enough. The
map always labels it **configured Trusted Zone location**, never GeoIP.

## How a location is worked out {#resolution}

1. If the address belongs to a **Trusted Zone**, the location is the zone name. In notifications the network reads
   *Home — Trusted Zone*.
2. If it is another private or local address, it reads *Private network*.
3. If it is a public address, the server's own **GeoIP database** (MaxMind format) is used. A City database gives an
   approximate place and point. A Country database gives only the country, shown as a dashed country-level circle.

> [!NOTE]
> **Privacy** Sign-in addresses are never sent to Google Maps, the tile server or any other geolocation service. Private
> addresses are never looked up at all. GeoIP is approximate: mobile networks and VPNs often appear somewhere else.

## Sign-in map {#map}

**My account → Sign-in security** shows your own sign-ins:

- the map;
- **Recent sign-ins**, with time, location and network, IP address, device and risk;
- **Recognised devices**.

Choose **30 days**, **90 days** or **1 year**.

![Sign-in map with a Trusted Zone pin, GeoIP points and the recent sign-ins](../images/screenshots/security-signin-map.png)

Who can see what:

| Person | Sees |
| --- | --- |
| Everyone | Their own sign-ins, map and devices, with full IP addresses. |
| A delegate with the *membership* scope of a family group | The members of that group. |
| Main administrator | Everyone (also under Settings → Activity & health → Sign-in map & Trusted Zones). |

Routine notifications show only the approximate location and network. For a Trusted Zone they show a shortened private
address (for example `192.168.x.10`). The full public address is under **View Security Details** in the app.

### Map tiles {#tiles}

The map is drawn with Leaflet, which is bundled with the app, and **online map tiles**. There is no offline tile server.
The browser downloads ordinary picture tiles from the server in **Settings → Security → Map tile server** (default
OpenStreetMap, `https://tile.openstreetmap.org/{z}/{x}/{y}.png`, with the credit line from *Map attribution*). The tile
server sees which map area is shown, like any web map. It never receives your sign-in addresses.

Turn **Sign-in map** off to show only the list.

## Risk {#risk}

Every successful sign-in gets an explainable risk level. Open **Why** to see the reasons.

| Example | Usual level |
| --- | --- |
| Home + recognised device | **Normal** |
| Home + new device | **Low** |
| Known public place + recognised device | **Normal** |
| New country, or a new device on a public network | **Warning** |
| Impossible travel: far away from the previous sign-in, faster than a plane (needs City-level GeoIP) | **High** — you and the administrators get an *Unusual sign-in* notification |

The signals used are: Trusted Zone, recognised device, sign-in method (passkey, authenticator code, single sign-on or
password only), GeoIP country and location history, and unusual changes of location.

> [!IMPORTANT]
> Risk is a hint. A sign-in is **never** blocked only because GeoIP says the location changed. Blocking by country
> is a separate, deliberate setting: see [country and IP rules](security-access.md#country-policy).

## Recognised devices {#devices}

A device is recognised by a random, long-lived cookie stored in that browser or app; only a hash of it is kept on the
server. The list shows each device's name, first and last use, active sessions and last address. **This device** marks
the one you are using.

To end one session without distrusting the device, use **My account → Password & security → Sessions**.

## Mark Unrecognized {#unrecognized}

Use this when you do not recognise a device.

1. Click **Mark Unrecognized** next to the device and confirm.
2. Personal DM then:
   - ends every active session of that device;
   - removes its recognition (its cookie is never trusted again: the next sign-in counts as a new device);
   - records a security event in the audit log;
   - sends you a security notification.
3. It then **offers** next steps. None of them is done automatically:
   - **Sign out all other sessions**;
   - **Change password**;
   - **Review passkeys**;
   - **Review linked sign-in methods** (Google, authentik);
   - **Review recent sign-ins**.

![Mark Unrecognized and the suggested next steps](../images/screenshots/security-devices.png)

Passkeys, the authenticator app and the password stay as they are until you change them.

## Retention {#retention}

Sign-in records, map points and device history follow the security log retention: **1 year** by default (*Login audit
retention* in Settings → Security). Devices that still have an active session are never removed by the cleanup.
