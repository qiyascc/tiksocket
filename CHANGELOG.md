# Changelog

## 0.1.0

First public release.

- QR login with the QR printed in the terminal, like Baileys, plus cookie login
- Native handling of TikTok's "verify it's you" step: read the prompt, enter the code, press its buttons
- Encrypted multi file auth state (`use_multi_file_auth_state`) and multi account support
- Video posts and photo posts (1 to 35 photos, swipeable) with title, caption, hashtags and music search
- Direct messages: list chats, read messages, send text with idempotency keys, live `messages.upsert` events
- Event emitter API: `qr`, `qr.status`, `verify`, `connection.update`, `creds.update`, `chats.update`, `messages.upsert`, `messages.sent`, `posts.upsert`
- CLI: `login`, `whoami`, `logout`, `accounts`, `post video`, `post photos`, `chats`, `messages`, `send`, `listen`, `serve`
- Web UI, REST API, Server Sent Events and WebSocket stream on port 8787 with token auth
- Retries with backoff, selector fallbacks, popup dismissal, logout and rate limit detection, screenshots on failure
- Docker image and compose file
