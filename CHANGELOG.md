# Changelog

## 0.2.0

- People: profile lookup, user search, followers and following lists, relationship check, follow, unfollow, block, unblock, remove a follower
- Content: post details and stats, a user's posts (your own through TikTok Studio, private ones included), comments, like, favorite, repost, comment, reply, like and delete comments, share a post to a chat, video download
- Your posts: delete, pin, who can see it, comments on or off
- Profile: name, username, bio, photo, private or public account
- Discover: search videos, hashtags and their posts, For You and Explore feeds, notifications
- Messages: start a chat or a message request from a username, list, accept and delete message requests, react, reply to a message
- CLI commands, REST endpoints and web UI sections for all of the above
- New typed models (`User`, `Post`, `Comment`, `Hashtag`, `Notice`, `Page`, `ActionResult`) and errors (`ActionFailed`, `PrivateAccount`, `NotSupported`)
- New events `action.done` and `comments.upsert`
- Reads that TikTok only answers for its own page code are captured from the page instead of called directly
- The user agent now matches the real Chromium version and operating system, so TikTok answers comment, post detail and post list requests

## 0.1.1

- Uploads close TikTok's "Turn on automatic content checks?" prompt with its own Cancel button before writing the caption, so the page is never blocked
- The posted id is read from TikTok's publish response, and the content page fallback skips pinned posts

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
