# TikSocket: the Baileys alternative for TikTok

[![CI](https://github.com/qiyascc/tiksocket/actions/workflows/ci.yml/badge.svg)](https://github.com/qiyascc/tiksocket/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Playwright](https://img.shields.io/badge/built%20on-Playwright-2EAD33)

**TikSocket** is an unofficial TikTok library that works the way [Baileys](https://github.com/WhiskeySockets/Baileys) works for WhatsApp:
you scan a QR code once, the session is saved, and from then on your code can **post videos and photo carousels with music, read and send direct messages, follow people, like, comment, repost, edit your profile, search, read feeds and notifications** and listen to new messages as events.

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
- [What TikTok web allows](#what-tiktok-web-allows)
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
| Direct messages | List chats, read messages (text, stickers, shared videos, images), send text, start new chats and message requests, accept or delete requests, react, reply to a message, idempotent sends |
| People | Profile lookup, user search, followers and following lists, relationship check, follow, unfollow, block, unblock, remove a follower |
| Content | Post details and stats, a user's posts, comments, like, favorite, repost, comment, reply, like and delete comments, share a post to a chat, download videos |
| Your posts | Delete, pin, change who can see a post and whether comments are on |
| Profile | Change name, username, bio and photo, switch the account between private and public |
| Discover | Search videos, hashtags and their posts, For You and Explore feeds, notifications (likes, comments, follows, mentions) |
| Live events | `messages.upsert`, `chats.update`, `connection.update` and more, delivered to handlers, SSE and WebSocket |
| CLI | 50 commands, from `login` and `post photos` to `follow`, `comment`, `profile`, `feed` and `serve` |
| Server | Web UI, REST API, token auth, Server Sent Events, WebSocket, multi account |
| Robustness | Page load retries with backoff, selector fallbacks, popup dismissal, click verification, logout and rate limit detection, failure screenshots |
| Deploy | Dockerfile and docker compose, headless by default, proxy support |

## What TikTok web allows

TikSocket only does what the TikTok website itself lets a logged in person do. Everything else is marked as app only.

Status key: **live** means checked against tiktok.com with a real account, **ready** means built on the web controls and TikTok's own web responses, covered by offline tests, and waiting for wider live use. Mutating actions were not run against a real account during development on purpose.

| Feature | Web | Status | Python |
| --- | --- | --- | --- |
| QR login, verify step, cookie login | yes | live | `request_qr`, `submit_code`, `login_with_cookies` |
| Post a video, sound search | yes | live | `post_video` |
| Post 1 to 35 photos as a swipe post with music | yes | live | `post_photos` |
| List chats, read messages, listen | yes | live | `chats`, `messages`, `start_listening` |
| Send a text message | yes | live (refused until the request is accepted) | `send_message` |
| Start a chat or send a message request | yes | ready | `start_chat` |
| Message requests: list, accept, delete | business inbox | ready | `message_requests`, `accept_request`, `delete_request` |
| React to a message, reply to a message | yes | ready | `react`, `reply_to` |
| Images, voice notes, files in chats | no | app only | |
| Profile lookup | yes | live | `get_user` |
| Search users | yes | live | `search_users` |
| Followers and following lists | yes | live | `followers`, `following` |
| Relationship check | yes | live | `relationship` |
| Follow, unfollow | yes | ready | `follow`, `unfollow` |
| Block, unblock | yes | ready | `block`, `unblock` |
| Remove a follower | yes | ready | `remove_follower` |
| Post details and stats | yes | live | `get_post` |
| A user's posts, your own posts | yes | live | `user_posts` |
| Comments of a post | yes | live | `comments` |
| Like, unlike | yes | ready | `like`, `unlike` |
| Favorite, unfavorite | yes | ready | `favorite`, `unfavorite` |
| Repost, undo repost | yes, on other people's posts | ready | `repost`, `undo_repost` |
| Comment, reply, like a comment, delete your comment | yes | ready | `comment`, `reply_comment`, `like_comment`, `delete_comment` |
| Share a post to a chat | yes | ready | `share_to_chat` |
| Download a video | yes | live | `download` |
| Delete your post | yes, through TikTok Studio | ready | `delete_post` |
| Who can see your post, comments on or off | yes, through TikTok Studio | ready | `post_settings` |
| Pin or unpin your post | depends on the account | ready, raises `NotSupported` when web hides it | `pin_post`, `unpin_post` |
| Change name, username, bio, photo | yes | ready | `update_profile` |
| Private or public account | yes, in settings | ready | `set_private` |
| Website link in bio | no | app only | |
| Search videos and photo posts | yes | live | `search_posts` |
| Hashtag info and posts | yes | live | `hashtag`, `hashtag_posts` |
| For You and Explore feeds | yes | live | `feed` |
| Notifications | yes | live | `notifications` |
| Stories, duets, stitches, LIVE | no | app only | |

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

People, content and profile:

```bash
tiksocket user @tiktok
tiksocket search-users "real estate baku"
tiksocket followers @someone --count 50
tiksocket following
tiksocket relation @someone
tiksocket follow @someone
tiksocket unfollow @someone
tiksocket block @spammer
tiksocket remove-follower @someone

tiksocket post-info https://www.tiktok.com/@user/video/7600000000000000000
tiksocket posts @someone --limit 20
tiksocket comments https://www.tiktok.com/@user/video/7600000000000000000
tiksocket like https://www.tiktok.com/@user/video/7600000000000000000
tiksocket favorite https://www.tiktok.com/@user/video/7600000000000000000
tiksocket repost https://www.tiktok.com/@user/video/7600000000000000000
tiksocket comment https://www.tiktok.com/@user/video/7600000000000000000 "Great view"
tiksocket reply https://www.tiktok.com/@user/video/7600000000000000000 7600000000000000001 "Thank you"
tiksocket download https://www.tiktok.com/@user/video/7600000000000000000 -o clip.mp4
tiksocket share https://www.tiktok.com/@user/video/7600000000000000000 @friend

tiksocket post-settings https://www.tiktok.com/@me/video/7600000000000000000 --who friends --comments off
tiksocket pin https://www.tiktok.com/@me/video/7600000000000000000
tiksocket delete-post https://www.tiktok.com/@me/video/7600000000000000000

tiksocket profile --name "My Shop" --bio "Open 9 to 6" --avatar logo.jpg
tiksocket privacy private

tiksocket search-posts "baku apartment"
tiksocket hashtag baku --posts 10
tiksocket feed --kind explore --count 5
tiksocket notifications --kind comment

tiksocket new-chat @someone "Hello, is this still available?"
tiksocket requests
tiksocket accept-request 0:1:111:222
tiksocket react 0:1:111:222 12 "❤️"
tiksocket reply-message 0:1:111:222 12 "Yes, it is"
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
- read chats, reply and start new chats
- open profiles, follow, block, list followers and posts, search users
- open a post, like, favorite, repost, comment, reply, download, and manage your own posts
- edit your profile and switch the account private or public
- browse the For You and Explore feeds, search videos and hashtags, read notifications and message requests
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
| `action.done` | `ActionResult(action, target, changed, detail)` after follow, like, repost, block and other actions that changed something |
| `comments.upsert` | `Comment` after you comment or reply |
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
| `await start_chat(username, text, client_id="")` | Opens a chat from the profile and sends text, returns `(chat_id, SendResult)` |
| `await message_requests()` | `list[Chat]` waiting in the requests folder |
| `await accept_request(chat_id)` / `await delete_request(chat_id)` | Answer a message request |
| `await react(chat_id, message_id, emoji)` | React to a message with one of TikTok's quick emoji |
| `await reply_to(chat_id, message_id, text, client_id="")` | Reply to a specific message |
| `start_listening(interval=25, history=False)` | Background task that emits `messages.upsert` |

People:

| Method | Description |
| --- | --- |
| `await get_user(username)` | `User` with bio, avatar, counts, privacy and your relation |
| `await search_users(query, cursor="0")` | `Page[User]`, pass `page.cursor` back for more |
| `await followers(username="", cursor="0", count=30)` | `Page[User]`, your own when `username` is empty |
| `await following(username="", cursor="0", count=30)` | `Page[User]` |
| `await relationship(username)` | `{"following", "friends", "relation", "private"}` |
| `await follow(username)` / `await unfollow(username)` | `ActionResult`, `changed=False` when it was already so |
| `await block(username)` / `await unblock(username)` | `ActionResult` |
| `await remove_follower(username)` | `ActionResult` |

Content:

| Method | Description |
| --- | --- |
| `await get_post(link_or_id)` | `Post` with stats, your like and favorite state, music, video and image links |
| `await user_posts(username="", limit=30)` | `list[Post]`, your own posts come from TikTok Studio and include private ones |
| `await comments(post, limit=50)` | `list[Comment]` |
| `await like(post)` / `await unlike(post)` | `ActionResult` |
| `await favorite(post)` / `await unfavorite(post)` | `ActionResult` |
| `await repost(post)` / `await undo_repost(post)` | `ActionResult` |
| `await comment(post, text)` | `Comment`, up to 150 characters |
| `await reply_comment(post, comment_id, text)` | `Comment` |
| `await like_comment(post, comment_id)` | `ActionResult` |
| `await delete_comment(post, comment_id)` | `ActionResult`, your own comments only |
| `await share_to_chat(post, username)` | Sends the post into a chat with someone in your share list |
| `await download(post, target=None)` | Video bytes, or the saved `Path` when `target` is given |
| `await delete_post(post)` | Deletes your post through TikTok Studio |
| `await pin_post(post)` / `await unpin_post(post)` | Pins or unpins, `NotSupported` when web does not offer it |
| `await post_settings(post, who_can_view="", comments=None)` | `who_can_view` is `everyone`, `friends` or `only_me` |

Profile and discovery:

| Method | Description |
| --- | --- |
| `await update_profile(nickname=None, username=None, bio=None, avatar=None)` | Changes only what you pass, `avatar` is a path or bytes, returns the new `User` |
| `await set_private(private)` | Private or public account |
| `await search_posts(query, cursor="0")` | `Page[Post]` |
| `await hashtag(name)` | `Hashtag(id, name, description, videos, views)` |
| `await hashtag_posts(name, limit=30)` | `list[Post]` |
| `await feed(kind="foryou", count=10)` | For You or `explore` feed |
| `await notifications(count=30, kind="")` | `list[Notice]`, filter with `like`, `comment`, `follow`, `mention` |

Posts and comments accept a full link (`https://www.tiktok.com/@user/video/123`, `/photo/` links too) or a bare post id. Users accept `@name`, `name` or a profile link.
| `await close()` | Closes the browser |

`dry_run=True` fills in everything on TikTok's upload page (files, title, caption, sound) and stops before pressing Post. Use it to test.

### Models

- `Profile(id, username, nickname, avatar)`
- `Chat(id, name, preview, date, unread, avatar, peer_id)`
- `Message(id, chat_id, kind, text, from_me, at, image, thumb, server_id, reply, failed)`, where `kind` is one of `text`, `image`, `sticker`, `video_share`, `unsupported`
- `PostResult(ok, id, kind, url, sound)`
- `User(id, sec_uid, username, nickname, bio, avatar, verified, private, link, followers, following, likes, videos, friends, relation)` with `is_following` and `is_friend`
- `Post(id, kind, url, author, caption, created, plays, likes, comments, shares, saves, reposts, liked, saved, private, pinned, comments_off, cover, play_url, download_url, duration, music, images, hashtags)`
- `Comment(id, post_id, text, author, author_nickname, likes, replies, created, liked, reply_to)`
- `Hashtag(id, name, description, videos, views)`
- `Notice(id, kind, type_id, created, read, users, post_id, text)`
- `Page(items, cursor, has_more, total)`
- `ActionResult(ok, action, target, changed, detail)`
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
| POST | `/api/accounts/{name}/chats` | `{"username": "...", "text": "...", "client_id": "..."}` | Start a chat or send a message request |
| GET | `/api/accounts/{name}/requests` | | Message requests |
| POST, DELETE | `/api/accounts/{name}/requests/{chat}` | | Accept or delete a request |
| POST | `/api/accounts/{name}/chats/{chat}/messages/{message}/react` | `{"emoji": "❤️"}` | React |
| POST | `/api/accounts/{name}/chats/{chat}/messages/{message}/reply` | `{"text": "..."}` | Reply to a message |
| GET | `/api/accounts/{name}/users/{user}` | | Profile |
| GET | `/api/accounts/{name}/users/{user}/followers` and `/following` | `?cursor=&count=` | People lists |
| GET | `/api/accounts/{name}/users/{user}/relation` | | Relationship |
| GET | `/api/accounts/{name}/users/{user}/posts` | `?limit=` | Posts of a user |
| POST, DELETE | `/api/accounts/{name}/users/{user}/follow` | | Follow, unfollow |
| POST, DELETE | `/api/accounts/{name}/users/{user}/block` | | Block, unblock |
| DELETE | `/api/accounts/{name}/users/{user}/follower` | | Remove a follower |
| GET | `/api/accounts/{name}/search/users` and `/search/posts` | `?q=&cursor=` | Search |
| GET | `/api/accounts/{name}/hashtags/{tag}` | `?posts=10` | Hashtag and its posts |
| GET | `/api/accounts/{name}/feed` | `?kind=foryou or explore&count=` | Feeds |
| GET | `/api/accounts/{name}/notifications` | `?count=&kind=` | Notifications |
| GET | `/api/accounts/{name}/post` | `?post=<link or id>` | Post details |
| GET | `/api/accounts/{name}/post/comments` | `?post=&limit=` | Comments |
| GET | `/api/accounts/{name}/post/download` | `?post=` | Video file |
| POST | `/api/accounts/{name}/post/{action}` | `{"post": "...", ...}` | `like`, `unlike`, `favorite`, `unfavorite`, `repost`, `unrepost`, `comment` (`text`), `reply` (`comment_id`, `text`), `like-comment`, `delete-comment` (`comment_id`), `share` (`username`), `settings` (`who_can_view`, `comments`), `pin`, `unpin`, `delete` |
| PATCH | `/api/accounts/{name}/profile` | `{"name", "username", "bio", "avatar": "<base64>"}` | Edit your profile |
| POST | `/api/accounts/{name}/privacy` | `{"private": true}` | Private or public account |
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
- the browser reports its real Chromium version and operating system as its user agent; TikTok silently returns empty answers for comments, post details and post lists when the two disagree
- every follow, like, comment or profile change waits for TikTok's own JSON confirmation of that action, and `ActionResult.changed` is `False` when nothing needed to change

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
| `NotFound` | `not_found` | Chat, user, post or comment not found |
| `BadInput` | `bad_input` | Invalid arguments |
| `ActionFailed` | `action_failed` | TikTok did not confirm a follow, like, comment or other action |
| `PrivateAccount` | `private` | The account is private |
| `NotSupported` | `not_supported` | TikTok web does not offer this, use the app |

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
- **Website link in bio**: the web profile editor has no link field, add it in the app.
- **Duets, stitches, LIVE**: app only.
- **Signed requests**: some TikTok web endpoints only answer requests made by TikTok's own page code. TikSocket reads those by opening the page and catching TikTok's own responses, which is slower than a direct call but keeps working.
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

**Can I follow, like and comment with Python?**
Yes. `follow`, `like`, `favorite`, `repost`, `comment` and `reply_comment` press the same buttons a person presses and wait for TikTok's own confirmation, so a returned result means TikTok accepted it.

**How do I get followers or comments as data?**
`followers`, `following`, `comments`, `user_posts`, `search_users`, `search_posts`, `hashtag_posts`, `feed` and `notifications` return typed objects, as JSON from the CLI with `--json` and from the REST API.

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
