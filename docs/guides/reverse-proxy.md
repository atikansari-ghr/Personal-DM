<!-- audience: admin -->
# Reverse proxy (Nginx Proxy Manager or Pangolin)

The app listens on HTTP inside the LXC (default `127.0.0.1:8000`; use `--bind 0.0.0.0:8000` or `PD_BIND` when the proxy runs elsewhere — then restrict port 8000 to the proxy with a firewall). The proxy terminates HTTPS.

## Application settings {#app}

In `/etc/personaldocs/personaldocs.env`:

```
PD_PUBLIC_ORIGIN=https://docs.example.com
PD_ALLOWED_HOSTS=docs.example.com
PD_BEHIND_PROXY=1
PD_TRUSTED_PROXY_IPS=10.0.0.5        # the proxy's address (or CIDR), for real client IPs
```

The real client IP drives the login audit, GeoIP, the country/IP access policy and traffic analytics. Only connections from
`PD_TRUSTED_PROXY_IPS` may set `X-Forwarded-For`; see [Security & access](security-access.md#real-ip).

Then `systemctl restart personaldocs-web`.

## HTTPS headers and HSTS {#hsts}

With an `https://` `PD_PUBLIC_ORIGIN` the app sends `Strict-Transport-Security` with one year (`PD_HSTS_SECONDS`, default 31536000; `0` turns it off; `PD_HSTS_INCLUDE_SUBDOMAINS=1` adds `includeSubDomains`). Django sends it only on requests it sees as HTTPS, so behind a proxy keep `PD_BEHIND_PROXY=1` and make the proxy send `X-Forwarded-Proto: https`. Lower the value while you are still testing a new domain: browsers remember HSTS for the whole period.

Settings → Security → Overview checks this from outside as part of **Internet Ready**: valid certificate, HTTP→HTTPS redirect (*Force SSL* in NPM), Secure cookies, security headers and HSTS. See [Internet Ready](security-center.md#internet-ready).

## Opening the app by IP on the home network {#local}

The app only answers to its public domain, so `http://<container-ip>:8000` shows **Bad Request (400)** by design. To also use it
directly on a trusted home network (for example while DNS or the proxy is not ready), run `sudo personaldocs local-access on`.
It sets `PD_LOCAL_ORIGINS=http://<container-ip>:<port>`. On that address only, sign-in cookies are sent without the HTTPS-only flag;
the public HTTPS address keeps full protection. Traffic on the plain-HTTP address is not encrypted, and camera upload, installing
as an app and offline copies need HTTPS. Give the container a fixed IP; `sudo personaldocs local-access off` turns it off again.

## Nginx Proxy Manager {#npm}

Proxy host: domain `docs.example.com`, scheme `http`, forward host = LXC IP, port 8000, *Websockets* not required, *Block common exploits* on. SSL: request a certificate, *Force SSL*, *HTTP/2*. Advanced tab:

```
client_max_body_size 1024m;
proxy_request_buffering off;
proxy_read_timeout 600s;
proxy_send_timeout 600s;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

Set `client_max_body_size` at least as large as the app's maximum upload size.

## Pangolin {#pangolin}

Create an HTTP resource for `docs.example.com` targeting the LXC IP and port 8000 through your Newt/WireGuard site. Pangolin forwards `X-Forwarded-*` headers. If Pangolin's own authentication (SSO) is enabled for the resource, add bypass rules for:

- `/s/*` — public share links (they have their own expiry/password),
- `/api/auth/google/callback` — Google sign-in return,
- `/api/auth/authentik/callback` — authentik sign-in return (if you use it),
- optionally `/manifest.webmanifest`, `/sw.js`, `/icon*` for PWA installation.

Never bypass `/api/*` as a whole: the app's own sign-in protects it, and the outer gate is an extra layer.

## Requirements checklist {#checklist}

- HTTPS everywhere (required for secure cookies, HSTS, PWA install, camera, Google and authentik sign-in).
- `X-Forwarded-Proto` passed to the app (HTTPS detection, Secure cookies and HSTS).
- Large uploads and long requests allowed (exports and imports stream for minutes).
- Range requests passed through (PDF previews, resumable downloads).
- The exact public origin configured in the app (CSRF and Google callback depend on it).
