# Telegram notifications

## Setup {#setup}

Administrator:

1. In Telegram, talk to **@BotFather**, send `/newbot`, and follow the steps. Copy the token.
2. Settings → Connections → Telegram: paste the token (stored encrypted), enter the bot username (without @), enable, save.
3. **Test connection** checks the token.

The server polls Telegram for link codes; no inbound webhook or open port is needed.

## Linking your account {#linking}

Each person: **Settings → My account → Notifications → Telegram → Get link code**, then send `/start CODE` to the bot from **your own** Telegram (or tap *Open Telegram*). Press *I've sent it — check*. Codes expire after 15 minutes and work once, so nobody can link someone else's chat. Telegram requires that you message the bot first.

## Troubleshooting {#troubleshooting}

- *Unauthorized*: the bot token is wrong or was revoked.
- Not linked after sending: make sure you messaged the right bot in a private chat and the code has not expired.
