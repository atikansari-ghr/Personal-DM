<!-- audience: admin -->
# Email (SMTP)

## Setup {#setup}

Settings → Connections → Email (SMTP):

| Setting | Example |
|---|---|
| SMTP host | `smtp.example.com` |
| Port | `587` (STARTTLS) or `465` (SSL/TLS) |
| Security | STARTTLS / SSL/TLS |
| Username / password | your mailbox or relay credentials (password stored encrypted) |
| From address | `documents@example.com` |

Turn on **Email (SMTP) enabled**, save, then **Send test email to me** (your profile needs an email address).

Gmail and Microsoft 365 usually require an app password or a relay; check your provider's current rules.

## Used for {#uses}

Expiry reminders, other notifications and password-reset links. Without SMTP, users without email must ask the administrator to reset passwords.

## Troubleshooting {#troubleshooting}

- *Authentication failed*: check username/app password.
- *Connection timed out*: the LXC may block outbound port 587/465; check the firewall.
- Delivery problems are listed in **Notifications → Delivery history** (errors are shown without passwords).
