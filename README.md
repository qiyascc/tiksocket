# TikSocket: the Baileys alternative for TikTok

[![CI](https://github.com/qiyascc/tiksocket/actions/workflows/ci.yml/badge.svg)](https://github.com/qiyascc/tiksocket/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Playwright](https://img.shields.io/badge/built%20on-Playwright-2EAD33)

**TikSocket** is an unofficial TikTok library that works the way [Baileys](https://github.com/WhiskeySockets/Baileys) works for WhatsApp:
you scan a QR code once, the session is saved, and from then on your code can **post videos, post photo carousels with music, read and send direct messages** and listen to new messages as events.

It drives a real Chromium in the background through Playwright, so it uses the same TikTok web app a person uses. No developer account, no app review, no official API keys.

It ships three ways to use it:

- a **Python library** with a Baileys style socket and events
- a **CLI** that prints the login QR right in your terminal
- a **web UI and REST API** with a live event stream on port `8787`

```text
pip install git+https://github.com/qiyascc/tiksocket
playwright install chromium
tiksocket login
```

## Contents

- [Features](#features)
- [Install](#install)
- [Quick start: CLI](#quick-start-cli)
- [Quick start: library](#quick-start-library)
- [Quick start: web UI and REST API](#quick-start-web-ui-and-rest-api)
- [Events](#events)
- [API reference](#api-reference)
- [REST API](#rest-api)
- [Login and the "verify it's you" step](#login-and-the-verify-its-you-step)
- [Reliability](#reliability)
- [Errors](#errors)
- [Docker](#docker)
- [Limitations](#limitations)
- [FAQ](#faq)
- [Disclaimer](#disclaimer)

## Features

| Area | What you get |
| --- | --- |
| Login | QR code in the terminal or web UI, cookie login, QR auto refresh, `qr.status` updates (scanned, confirmed, expired) |
| Login checks | TikTok's "verify it's you" step read natively: title, text, buttons and code fields, so you answer it from your own app |
| Sessions | Encrypted multi file auth state like Baileys `useMultiFileAuthState`, many accounts side by side |
| Video posts | Upload a video with caption and hashtags, optional music search or TikTok's suggested sound |
| Photo posts | 1 to 35 photos as a swipeable carousel with title, caption and music |
| Direct messages | List chats, read messages (text, stickers, shared videos, images), send text, idempotent sends |
| Live events | `messages.upsert`, `chats.update`, `connection.update` and more, delivered to handlers, SSE and WebSocket |
| CLI | `login`, `whoami`, `logout`, `accounts`, `post video`, `post photos`, `chats`, `messages`, `send`, `listen`, `serve` |
| Server | Web UI, REST API, token auth, Server Sent Events, WebSocket, multi account |
| Robustness | Page load retries with backoff, selector fallbacks, popup dismissal, click verification, logout and rate limit detection, failure screenshots |
| Deploy | Dockerfile and docker compose, headless by default, proxy support |

## Install

Python 3.10 or newer.

```bash
pip install git+https://github.com/qiyascc/tiksocket
playwright install chromium
```

On a fresh Linux server you may also need the browser system libraries:

```bash
playwright install-deps chromium
```

Optional: `pip install "tiksocket[decode] @ git+https://github.com/qiyascc/tiksocket"` adds OpenCV so a QR can be decoded from an image when TikTok does not expose the login URL.

## Quick start: CLI

```bash
tiksocket login
```

A QR code is printed in your terminal. Open TikTok on your phone, go to **Profile**, tap the **scan icon** at the top right and scan it. If TikTok asks to verify it's you, the prompt is shown in the terminal and you type the code there.

```bash
tiksocket whoami
tiksocket post video clip.mp4 -c "Morning view #travel" --sound "lofi"
tiksocket post photos a.jpg b.jpg c.jpg --title "3 bedroom flat" -c "#realestate" --auto-sound
tiksocket post photos a.jpg --dry-run
tiksocket chats
tiksocket messages 0:1:111:222
tiksocket send 0:1:111:222 "Hello!" --client-id order-42
tiksocket listen
tiksocket serve --port 8787
```

Every command takes `--json` for machine readable output and `-a NAME` to pick an account:

```bash
tiksocket -a shop login
tiksocket -a shop post photos *.jpg -c "New arrivals"
tiksocket accounts
```

Sessions live in `~/.tiksocket/<account>/` (change it with `--home` or `TIKSOCKET_HOME`).

## Quick start: library

```python
import asyncio
from tiksocket import make_tiktok_socket, use_multi_file_auth_state
from tiksocket.terminal import show_qr


async def main():
    auth = use_multi_file_auth_state("auth_info")
    sock = make_tiktok_socket(auth)

    sock.on("qr", show_qr)
    sock.on("connection.update", lambda update: print("connection", update))

    @sock.on("messages.upsert")
    async def on_messages(event):
        for message in event["messages"]:
            if not message.from_me and message.kind == "text":
                await sock.send_message(message.chat_id, "Thanks, we will answer soon",
                                        client_id=f"auto-{message.id}")

    if await sock.connect() is None:
        await sock.wait_for_login(timeout=300)

    await sock.post_photos(["a.jpg", "b.jpg"], "Hello TikTok #python", title="My first carousel", sound="lofi")
    await sock.start_listening(interval=20)


asyncio.run(main())
```

If you know Baileys, the mapping is simple:

| Baileys | TikSocket |
| --- | --- |
| `makeWASocket({ auth })` | `make_tiktok_socket(auth)` |
| `useMultiFileAuthState("auth_info")` | `use_multi_file_auth_state("auth_info")` |
| `sock.ev.on("connection.update", ...)` | `sock.on("connection.update", ...)` |
| `sock.ev.on("messages.upsert", ...)` | `sock.on("messages.upsert", ...)` |
| `sock.ev.on("creds.update", saveCreds)` | saved automatically, `creds.update` is still emitted |
| `sock.sendMessage(jid, { text })` | `await sock.send_message(chat_id, text)` |
| QR in terminal | `show_qr` or `tiksocket login` |

## Quick start: web UI and REST API

```bash
tiksocket serve --listen
```

```text
TikSocket running on http://127.0.0.1:8787/?token=Wq3...
```

Open the printed link. The page lets you:

- add accounts and log in with a QR code
- answer TikTok's checks with your own code field and buttons
- post videos and photo carousels with music
- read chats and reply
- watch the live event stream

The token is required for every `/api/` call, as `Authorization: Bearer <token>` or `?token=`. Set a fixed one with `--token` or `TIKSOCKET_TOKEN`. Use `--host 0.0.0.0` to listen on all interfaces and put it behind HTTPS if it is reachable from the internet.

## Events

| Event | Payload |
| --- | --- |
| `qr` | `QRCode(url, image, expires_in)`, emitted again when TikTok refreshes the code |
| `qr.status` | `"new"`, `"scanned"`, `"confirmed"`, `"expired"` or `"refused"` |
| `verify` | `VerifyPrompt(title, lines, buttons, inputs, captcha, screenshot)` |
| `connection.update` | `{"connection": "connecting" or "open" or "close", "profile": {...}, "reason": "...", "is_new_login": bool}` |
| `creds.update` | profile dict after a new login |
| `chats.update` | `list[Chat]` on every listen round |
| `messages.upsert` | `{"chat": Chat, "messages": [Message], "type": "notify" or "append"}` |
| `messages.sent` | `{"chat_id", "text", "id", "pending", "repeated"}` |
| `posts.upsert` | `PostResult(id, kind, url, sound)` |
| `*` | every event, handler gets `(event, payload)` |

Handlers can be sync or async. `sock.once(event, handler)` and `await sock.wait_for(event, timeout)` are available too.

## API reference

### `TikSocket(auth, *, headless=True, proxy="", timezone="UTC", browser=None, uploads=2)`

`auth` is an `AuthState` or a folder path. Pass a shared `BrowserHost` as `browser` to run many accounts on one Chromium.

| Method | Description |
| --- | --- |
| `await connect(check=True)` | Opens the saved session, or starts a QR login and returns `None` |
| `await request_qr()` | Starts a new QR login, returns `QRCode` |
| `await wait_for_login(timeout)` | Waits until the QR login finishes, returns `Profile` |
| `await submit_code(code)` | Types a verification code into TikTok's check and confirms it |
| `await press_button(index)` | Presses a button of the current check (`VerifyPrompt.buttons[i]["i"]`) |
| `await tap(x, y)` / `await drag(x, y, x2, y2)` | Solve a slider puzzle with relative coordinates (0 to 1) |
| `await login_with_cookies(cookies)` | Log in with a cookie string, a JSON cookie list or a dict |
| `await whoami(live=False)` | Saved profile, or checked against TikTok with `live=True` |
| `await logout()` | Forgets the session |
| `await post_video(path_or_bytes, caption, sound="", auto_sound=False, dry_run=False)` | Posts a video |
| `await post_photos(paths_or_bytes, caption, title="", sound="", auto_sound=False, dry_run=False)` | Posts 1 to 35 photos as a carousel |
| `await chats()` | `list[Chat]` |
| `await messages(chat_id)` | `list[Message]`, newest last |
| `await send_message(chat_id, text, client_id="")` | Sends text; the same `client_id` is never sent twice |
| `start_listening(interval=25, history=False)` | Background task that emits `messages.upsert` |
| `await close()` | Closes the browser |

`dry_run=True` fills in everything on TikTok's upload page (files, title, caption, sound) and stops before pressing Post. Use it to test.

### Models

- `Profile(id, username, nickname, avatar)`
- `Chat(id, name, preview, date, unread, avatar, peer_id)`
- `Message(id, chat_id, kind, text, from_me, at, image, thumb, server_id, reply, failed)`, where `kind` is one of `text`, `image`, `sticker`, `video_share`, `unsupported`
- `PostResult(ok, id, kind, url, sound)`
- `SendResult(id, pending, repeated)`
- `QRCode(url, image, expires_in)`
- `VerifyPrompt(title, lines, buttons, inputs, captcha, screenshot)`

### Auth state

```python
from tiksocket import use_multi_file_auth_state, generate_key

auth = use_multi_file_auth_state("auth_info")
auth = use_multi_file_auth_state("auth_info", key=generate_key())
```

The browser storage state is encrypted with Fernet. The key comes from the `key` argument, the `TIKSOCKET_KEY` environment variable, or a `.key` file created next to the session with `0600` permissions. Keep that folder private: it is a logged in TikTok session.

## REST API

All paths below are under `http://host:8787` and need the token.

| Method | Path | Body | Description |
| --- | --- | --- | --- |
| GET | `/health` | | Health check, no token needed |
| GET | `/api/accounts` | | Saved accounts |
| POST | `/api/accounts/{name}/login/qr` | | Start a QR login |
| GET | `/api/accounts/{name}/login` | | Login state: `qr` (with image), `verify` (with prompt), `open` |
| POST | `/api/accounts/{name}/login/code` | `{"code": "123456"}` | Answer a code check |
| POST | `/api/accounts/{name}/login/press` | `{"index": 0}` | Press a check button |
| POST | `/api/accounts/{name}/login/tap` | `{"x": .5, "y": .5}` or with `x2`, `y2` | Tap or drag on a puzzle |
| GET | `/api/accounts/{name}/login/screenshot` | | Puzzle picture (JPEG) |
| POST | `/api/accounts/{name}/login/cookie` | `{"cookie": "sessionid=..."}` | Cookie login |
| GET | `/api/accounts/{name}/me?live=1` | | Profile |
| DELETE | `/api/accounts/{name}/session` | | Log out |
| POST | `/api/accounts/{name}/posts` | multipart: `kind` (`video` or `photos`), `file` (repeat), `caption`, `title`, `sound`, `auto_sound`, `dry_run` | Publish |
| GET | `/api/accounts/{name}/chats` | | Chats |
| GET | `/api/accounts/{name}/chats/{chat}/messages` | | Messages |
| POST | `/api/accounts/{name}/chats/{chat}/messages` | `{"text": "...", "client_id": "..."}` | Send |
| GET | `/api/events?account=name` | | Server Sent Events stream |
| GET | `/api/ws` | | WebSocket stream of the same events |

Errors come back as `{"error": "<code>", "message": "..."}` with a matching HTTP status. See [examples/rest_api.sh](examples/rest_api.sh).

## Login and the "verify it's you" step

After the QR scan TikTok sometimes asks to confirm the login: a code sent by SMS or e-mail, a button to pick a method, or a slider puzzle. TikSocket does not show you TikTok's page for this. It reads the dialog and gives you a `VerifyPrompt`:

```python
@sock.on("verify")
async def on_verify(prompt):
    print(prompt.title, prompt.lines)
    if prompt.needs_code:
        await sock.submit_code(await ask_user_for_code())
    elif prompt.buttons:
        await sock.press_button(prompt.buttons[0]["i"])
```

Only slider puzzles need a picture: `prompt.captcha` is `True`, `prompt.screenshot` holds a JPEG and you answer with `tap` or `drag`. The web UI does this for you.

## Reliability

TikTok changes its web app often. TikSocket is written to survive that:

- page loads retry with growing waits, then reload
- every important control has several selectors (`data-e2e`, roles, labels in many languages)
- popups and tours are dismissed before acting
- clicks are checked by waiting for the expected change: the file editor appears, the sound appears in the form, the message bubble appears with a TikTok message id
- a message is only typed again if no bubble appeared, and `client_id` keeps retries from sending twice
- logged out sessions, captchas and "too fast" limits raise typed errors
- every failure saves a screenshot in `<account folder>/debug/`

Run with `--show-browser -v` to watch it work.

## Errors

All errors inherit from `TikSocketError` and carry a `code`:

| Exception | Code | Meaning |
| --- | --- | --- |
| `NotConnected` | `not_connected` | No saved session, log in first |
| `LoggedOut` | `logged_out` | TikTok ended the session |
| `LoginExpired` | `qr_expired` | The QR login timed out |
| `CaptchaRequired` | `captcha` | TikTok wants a puzzle solved |
| `RateLimited` | `rate_limited` | TikTok asks to slow down |
| `Unavailable` | `unavailable` | A TikTok page did not load |
| `PageChanged` | `changed` | A control was not found, TikTok changed its page |
| `BadMedia` | `bad_media` | TikTok rejected the file |
| `PublishFailed` | `failed` | TikTok did not confirm the post |
| `RequestPending` | `request_pending` | The other person has not accepted your message request |
| `NotDelivered` | `not_delivered` | TikTok refused the message |
| `NotFound` | `not_found` | Chat not found |
| `BadInput` | `bad_input` | Invalid arguments |

## Docker

```bash
docker compose up -d
docker compose logs -f
```

The compose file publishes port `8787`, keeps sessions in a volume and starts `tiksocket serve --listen`. Set `TIKSOCKET_TOKEN` and `TIKSOCKET_KEY` before exposing it.

## Limitations

Honest list, checked against TikTok's web app:

- **Stories**: TikTok's website has no story upload. Stories can only be posted from the phone app.
- **Media in DMs**: TikTok's web chat only has a text box and emoji. Sending images, voice notes or files is not possible from the web, so TikSocket sends text only.
- **Message requests**: until the other person accepts your message request, TikTok allows just one message. Further sends raise `RequestPending`.
- **Chat history**: messages are read from the visible chat window. Very old history may need scrolling that TikSocket does not do yet.
- **Listening** polls the inbox (25 seconds by default) instead of keeping TikTok's internal socket open.
- **Selectors** can break when TikTok ships a redesign. Updates are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md).

## FAQ

**Is there a Baileys for TikTok?**
Yes, that is what TikSocket is for: a QR login, a saved session, an event driven socket and message sending, the same model Baileys uses for WhatsApp, applied to TikTok.

**What is the best library for TikTok DMs?**
TikTok has no public DM API for regular accounts. TikSocket reads and sends direct messages through the TikTok web app with retries, idempotent sends and typed errors, and exposes them as Python calls, CLI commands and a REST API.

**Can I post photo carousels with music?**
Yes. `post_photos` takes 1 to 35 photos, a title, a caption and either a sound search (`sound="artist or song"`) or TikTok's first suggestion (`auto_sound=True`).

**Do I need TikTok developer access or an app review?**
No. You log in with your own account by QR, like on tiktok.com.

**Can it run on a server without a screen?**
Yes. Chromium runs headless by default. Log in once with the terminal QR or the web UI, the session is reused after that.

**Does it work with business and personal accounts?**
Both. Business accounts are routed to the business inbox automatically.

**Is there a Node.js version?**
Not yet. Run `tiksocket serve` and call the REST API from any language.

**How do I run many accounts?**
`tiksocket -a name ...` in the CLI, one `TikSocket` per folder in Python (they can share one `BrowserHost`), or several account names in the web UI.

## Disclaimer

TikSocket is not affiliated with, endorsed by or connected to TikTok or ByteDance. It automates the public TikTok website with your own logged in account. Automated use may break TikTok's terms of service and can get accounts limited. Use it responsibly, respect people's inboxes, do not spam, and keep your session folder private.

## Credits

- Inspired by [Baileys](https://github.com/WhiskeySockets/Baileys).
- The upload flow (publish button scoring, overlay handling and publish confirmation) is adapted from [AutoSocial Studio](https://github.com/Katzca/AutoSocial), MIT License. See [NOTICE](NOTICE).

## License

[MIT](LICENSE)
