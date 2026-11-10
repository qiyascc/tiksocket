from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

from . import __version__
from .auth import use_multi_file_auth_state
from .client import TikSocket
from .constants import DEFAULT_PORT
from .errors import TikSocketError
from .terminal import show_prompt, show_qr

DEFAULT_BASE = Path(os.environ.get("TIKSOCKET_HOME") or Path.home() / ".tiksocket")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tiksocket", description="TikSocket: the Baileys alternative for TikTok")
    parser.add_argument("--version", action="version", version=f"tiksocket {__version__}")
    parser.add_argument("-a", "--account", default=os.environ.get("TIKSOCKET_ACCOUNT", "default"),
                        help="account name, one folder per account")
    parser.add_argument("--home", default=str(DEFAULT_BASE), help="folder that holds all accounts")
    parser.add_argument("--show-browser", action="store_true", help="run Chromium with a visible window")
    parser.add_argument("--proxy", default=os.environ.get("TIKSOCKET_PROXY", ""), help="proxy URL for Chromium")
    parser.add_argument("--timezone", default=os.environ.get("TIKSOCKET_TZ", "UTC"))
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--captcha-timeout", type=float, default=float(os.environ.get("TIKSOCKET_CAPTCHA_TIMEOUT") or 600),
                        help="seconds to wait for a person to solve a TikTok captcha, 0 fails at once")
    parser.add_argument("--captcha-host", default=os.environ.get("TIKSOCKET_CAPTCHA_HOST", "127.0.0.1"),
                        help="address of the small captcha page the CLI opens when TikTok asks for one")
    parser.add_argument("--captcha-port", type=int, default=int(os.environ.get("TIKSOCKET_CAPTCHA_PORT") or 8788))
    parser.add_argument("--no-open", action="store_true", help="print the captcha link without opening a browser")
    parser.add_argument("--robot", action="store_true", default=os.environ.get("TIKSOCKET_HUMAN") == "0",
                        help="click and type instantly instead of moving and typing like a person")
    parser.add_argument("--human-speed", type=float, default=float(os.environ.get("TIKSOCKET_HUMAN_SPEED") or 1),
                        help="speed of the person-like mouse, typing and pauses, 2 is twice as fast")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="log in by scanning a QR code in the terminal")
    login.add_argument("--cookie", help="log in with a cookie string or JSON file instead of QR")
    login.add_argument("--timeout", type=int, default=300)

    who = sub.add_parser("whoami", help="show the logged in account")
    who.add_argument("--live", action="store_true", help="check the session against TikTok")
    sub.add_parser("logout", help="forget the saved session")
    sub.add_parser("accounts", help="list saved accounts")

    post = sub.add_parser("post", help="publish a video or photo post")
    kinds = post.add_subparsers(dest="kind", required=True)
    video = kinds.add_parser("video", help="post a video")
    video.add_argument("file")
    photos = kinds.add_parser("photos", help="post 1 to 35 photos as a swipe post")
    photos.add_argument("files", nargs="+")
    photos.add_argument("--title", default="")
    for item in (video, photos):
        item.add_argument("-c", "--caption", default="")
        item.add_argument("--sound", default="", help="search TikTok sounds and use the first result")
        item.add_argument("--auto-sound", action="store_true", help="use TikTok's first suggested sound")
        item.add_argument("--dry-run", action="store_true", help="fill everything but do not press Post")

    sub.add_parser("chats", help="list direct message chats")
    msgs = sub.add_parser("messages", help="show messages of a chat")
    msgs.add_argument("chat_id")
    send = sub.add_parser("send", help="send a text message")
    send.add_argument("chat_id")
    send.add_argument("text")
    send.add_argument("--client-id", default="", help="idempotency key, the same key is never sent twice")
    listen = sub.add_parser("listen", help="stream new incoming messages")
    listen.add_argument("--interval", type=float, default=25.0)
    listen.add_argument("--history", action="store_true", help="also print messages already in the inbox")

    add_web_commands(sub)

    serve = sub.add_parser("serve", help="run the web UI and REST API")
    serve.add_argument("--host", default=os.environ.get("TIKSOCKET_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("TIKSOCKET_PORT") or DEFAULT_PORT))
    serve.add_argument("--token", default=os.environ.get("TIKSOCKET_TOKEN", ""), help="API token, generated if empty")
    serve.add_argument("--listen", action="store_true", help="poll messages of every logged in account")
    return parser


def add_web_commands(sub) -> None:
    def cmd(name, text, *args):
        item = sub.add_parser(name, help=text)
        for arg in args:
            if isinstance(arg, tuple):
                item.add_argument(*arg[0], **arg[1])
            else:
                item.add_argument(arg)
        return item

    def opt(*flags, **kw):
        return flags, kw

    cmd("user", "show a TikTok profile", "username")
    cmd("search-users", "search TikTok users", "query", opt("--cursor", default="0"))
    for name in ("followers", "following"):
        cmd(name, f"list {name} of a user (yours by default)", opt("username", nargs="?", default=""),
            opt("--cursor", default="0"), opt("--count", type=int, default=30))
    cmd("relation", "show whether you follow a user", "username")
    for name, text in (("follow", "follow a user"), ("unfollow", "unfollow a user"), ("block", "block a user"),
                       ("unblock", "unblock a user"), ("remove-follower", "remove someone from your followers")):
        cmd(name, text, "username")
    cmd("post-info", "show a post with its stats", "post")
    cmd("posts", "list posts of a user (yours by default)", opt("username", nargs="?", default=""),
        opt("--limit", type=int, default=30))
    cmd("comments", "list comments of a post", "post", opt("--limit", type=int, default=50))
    for name, text in (("like", "like a post"), ("unlike", "remove your like"), ("favorite", "add a post to Favorites"),
                       ("unfavorite", "remove a post from Favorites"), ("repost", "repost a post"),
                       ("unrepost", "undo a repost"), ("delete-post", "delete your own post"),
                       ("pin", "pin your own post"), ("unpin", "unpin your own post")):
        cmd(name, text, "post")
    cmd("comment", "comment on a post", "post", "text")
    cmd("reply", "reply to a comment", "post", "comment_id", "text")
    cmd("like-comment", "like a comment", "post", "comment_id")
    cmd("delete-comment", "delete your own comment", "post", "comment_id")
    cmd("post-settings", "change who can see your post and comments", "post",
        opt("--who", choices=["everyone", "friends", "only_me"], default=""),
        opt("--comments", choices=["on", "off"], default=""))
    cmd("search-posts", "search TikTok videos and photo posts", "query", opt("--cursor", default="0"))
    cmd("hashtag", "show a hashtag and its posts", "name", opt("--posts", type=int, default=0))
    cmd("feed", "read the For You or Explore feed", opt("--kind", choices=["foryou", "explore"], default="foryou"),
        opt("--count", type=int, default=10))
    cmd("notifications", "list your notifications", opt("--count", type=int, default=30),
        opt("--kind", choices=["", "like", "comment", "follow", "mention", "system"], default=""))
    cmd("download", "download a video", "post", opt("-o", "--output", default=""))
    profile = cmd("profile", "change your name, username, bio or photo")
    profile.add_argument("--name")
    profile.add_argument("--username")
    profile.add_argument("--bio")
    profile.add_argument("--avatar", help="image file for the profile photo")
    cmd("privacy", "make your account private or public", opt("mode", choices=["private", "public"]))
    cmd("share", "share a post to a chat", "post", "username")
    cmd("new-chat", "message a user, this sends a message request if you are not friends", "username", "text",
        opt("--client-id", default=""))
    cmd("requests", "list message requests")
    cmd("accept-request", "accept a message request", "chat_id")
    cmd("delete-request", "delete a message request", "chat_id")
    cmd("react", "react to a message with an emoji", "chat_id", "message_id", "emoji")
    cmd("reply-message", "reply to a specific message", "chat_id", "message_id", "text", opt("--client-id", default=""))


def _stamp(value: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M") if value else ""


def _user_line(u) -> str:
    return f"@{u.username}  {u.nickname}  followers {u.followers}" + ("  (following)" if u.is_following else "")


def _post_line(p) -> str:
    return f"{p.url}  {p.kind}  likes {p.likes} comments {p.comments} plays {p.plays}  {p.caption[:60]}"


async def run_web_command(args, sock: TikSocket) -> bool:
    c = args.command
    simple = {"follow": sock.follow, "unfollow": sock.unfollow, "block": sock.block, "unblock": sock.unblock,
              "remove-follower": sock.remove_follower, "like": sock.like, "unlike": sock.unlike,
              "favorite": sock.favorite, "unfavorite": sock.unfavorite, "repost": sock.repost,
              "unrepost": sock.undo_repost, "delete-post": sock.delete_post, "pin": sock.pin_post,
              "unpin": sock.unpin_post}
    if c in simple:
        result = await simple[c](getattr(args, "username", None) or getattr(args, "post", ""))
        out(args, result, f"{result.action}: {'done' if result.changed else 'already so'} ({result.target})")
        return True
    if c == "user":
        u = await sock.get_user(args.username)
        out(args, u, f"{_user_line(u)}\nfollowing {u.following}  likes {u.likes}  videos {u.videos}\n{u.bio}")
    elif c == "search-users":
        page = await sock.search_users(args.query, args.cursor)
        out(args, page, "\n".join(_user_line(u) for u in page.items) + f"\nnext cursor: {page.cursor}")
    elif c in ("followers", "following"):
        method = sock.followers if c == "followers" else sock.following
        page = await method(args.username, args.cursor, args.count)
        out(args, page, "\n".join(_user_line(u) for u in page.items) + f"\nnext cursor: {page.cursor}")
    elif c == "relation":
        data = await sock.relationship(args.username)
        out(args, data, f"@{data['username']}: {'following' if data['following'] else 'not following'}"
                        + (", friends" if data["friends"] else ""))
    elif c == "post-info":
        p = await sock.get_post(args.post)
        out(args, p, f"{_post_line(p)}\nmusic: {p.music}  created {_stamp(p.created)}")
    elif c == "posts":
        rows = await sock.user_posts(args.username, args.limit)
        out(args, rows, "\n".join(_post_line(p) for p in rows) or "No posts")
    elif c == "comments":
        rows = await sock.comments(args.post, args.limit)
        out(args, rows, "\n".join(f"{m.id}  @{m.author}: {m.text}  ({m.likes} likes)" for m in rows) or "No comments")
    elif c == "comment":
        m = await sock.comment(args.post, args.text)
        out(args, m, f"Commented, id {m.id}")
    elif c == "reply":
        m = await sock.reply_comment(args.post, args.comment_id, args.text)
        out(args, m, f"Replied, id {m.id}")
    elif c in ("like-comment", "delete-comment"):
        method = sock.like_comment if c == "like-comment" else sock.delete_comment
        result = await method(args.post, args.comment_id)
        out(args, result, f"{result.action}: {'done' if result.changed else 'already so'}")
    elif c == "post-settings":
        comments = None if not args.comments else args.comments == "on"
        result = await sock.post_settings(args.post, args.who, comments)
        out(args, result, "Post settings saved")
    elif c == "search-posts":
        page = await sock.search_posts(args.query, args.cursor)
        out(args, page, "\n".join(_post_line(p) for p in page.items) + f"\nnext cursor: {page.cursor}")
    elif c == "hashtag":
        tag = await sock.hashtag(args.name)
        rows = await sock.hashtag_posts(args.name, args.posts) if args.posts else []
        out(args, {"hashtag": tag, "posts": rows},
            f"#{tag.name}  views {tag.views}  videos {tag.videos}\n" + "\n".join(_post_line(p) for p in rows))
    elif c == "feed":
        rows = await sock.feed(args.kind, args.count)
        out(args, rows, "\n".join(_post_line(p) for p in rows))
    elif c == "notifications":
        rows = await sock.notifications(args.count, args.kind)
        out(args, rows, "\n".join(f"{_stamp(n.created)}  {n.kind}  {', '.join('@' + u for u in n.users)}  {n.text[:60]}"
                                   for n in rows) or "No notifications")
    elif c == "download":
        target = await sock.download(args.post, args.output or None)
        if args.output:
            out(args, {"file": str(target)}, f"Saved {target}")
        else:
            sys.stdout.buffer.write(target)
    elif c == "profile":
        u = await sock.update_profile(nickname=args.name, username=args.username, bio=args.bio, avatar=args.avatar)
        out(args, u, f"Profile saved: {_user_line(u)}")
    elif c == "privacy":
        result = await sock.set_private(args.mode == "private")
        out(args, result, f"Account is {args.mode}" + ("" if result.changed else " already"))
    elif c == "share":
        result = await sock.share_to_chat(args.post, args.username)
        out(args, result, f"Shared to @{args.username}")
    elif c == "new-chat":
        chat_id, result = await sock.start_chat(args.username, args.text, args.client_id)
        out(args, {"chat_id": chat_id, **result.to_dict()}, f"Sent to @{args.username}, chat {chat_id}")
    elif c == "requests":
        rows = await sock.message_requests()
        out(args, rows, "\n".join(f"{r.id}  {r.name}  {r.preview}" for r in rows) or "No message requests")
    elif c in ("accept-request", "delete-request"):
        method = sock.accept_request if c == "accept-request" else sock.delete_request
        await method(args.chat_id)
        out(args, {"ok": True}, "Done")
    elif c == "react":
        await sock.react(args.chat_id, args.message_id, args.emoji)
        out(args, {"ok": True}, "Reacted")
    elif c == "reply-message":
        result = await sock.reply_to(args.chat_id, args.message_id, args.text, args.client_id)
        out(args, result, f"Replied, id {result.id}")
    else:
        return False
    return True


def dump(value) -> object:
    if is_dataclass(value):
        data = asdict(value)
        data.pop("screenshot", None)
        if isinstance(data.get("image"), bytes):
            data["image"] = None
        return data
    if isinstance(value, list):
        return [dump(item) for item in value]
    if isinstance(value, dict):
        return {k: dump(v) for k, v in value.items()}
    return value


def out(args, value, text: str = "") -> None:
    if args.json or not text:
        print(json.dumps(dump(value), ensure_ascii=False, indent=2, default=str))
    else:
        print(text)


def make_socket(args) -> TikSocket:
    auth = use_multi_file_auth_state(Path(args.home) / args.account)
    return TikSocket(auth, headless=not args.show_browser, proxy=args.proxy, timezone=args.timezone,
                     captcha_timeout=args.captcha_timeout, human=not args.robot, human_speed=args.human_speed)


async def ask(text: str) -> str:
    return (await asyncio.to_thread(input, text)).strip()


async def cmd_login(args, sock: TikSocket) -> int:
    if args.cookie:
        raw = Path(args.cookie).read_text(encoding="utf-8") if Path(args.cookie).is_file() else args.cookie
        profile = await sock.login_with_cookies(raw)
        out(args, profile, f"Logged in as @{profile.username}")
        return 0
    if sock.auth.exists and await sock.whoami(live=True):
        out(args, sock.profile, f"Already logged in as @{sock.profile.username}. Run logout first to switch.")
        return 0
    prompts: asyncio.Queue = asyncio.Queue()
    sock.on("qr", lambda qr: show_qr(qr, sock.auth.folder))
    sock.on("qr.status", lambda status: print(f"QR status: {status}"))
    sock.on("verify", prompts.put)
    await sock.request_qr()
    done = asyncio.ensure_future(sock.wait_for_login(args.timeout))
    while not done.done():
        waiter = asyncio.ensure_future(prompts.get())
        finished, _ = await asyncio.wait({done, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if waiter not in finished:
            waiter.cancel()
            break
        prompt = waiter.result()
        show_prompt(prompt)
        if prompt.captcha:
            continue
        answer = await ask("Code, button number, or Enter to keep waiting: ")
        if not answer:
            continue
        try:
            if answer.isdigit() and not prompt.inputs and int(answer) < len(prompt.buttons):
                await sock.press_button(int(answer))
            else:
                await sock.submit_code(answer)
        except TikSocketError as exc:
            print(f"Could not apply: {exc}")
    profile = await done
    out(args, profile, f"Logged in as @{profile.username} ({profile.nickname})")
    return 0


async def run(args) -> int:
    if args.command == "accounts":
        base = Path(args.home)
        rows = []
        for folder in sorted(base.iterdir()) if base.exists() else []:
            if (folder / "state.bin").exists():
                auth = use_multi_file_auth_state(folder)
                rows.append({"account": folder.name, **auth.load_profile()})
        out(args, rows, "\n".join(f"{r['account']}: @{r.get('username', '')}" for r in rows) or "No accounts yet")
        return 0
    if args.command == "serve":
        from .server import run_server

        await run_server(Path(args.home), host=args.host, port=args.port, token=args.token, listen=args.listen,
                         headless=not args.show_browser, proxy=args.proxy, timezone=args.timezone)
        return 0
    sock = make_socket(args)
    from .server.captcha import CaptchaPage

    page = CaptchaPage(sock, host=args.captcha_host, port=args.captcha_port, open_browser=not args.no_open).attach()
    try:
        if args.command == "login":
            return await cmd_login(args, sock)
        if args.command == "whoami":
            profile = await sock.whoami(live=args.live)
            if profile is None:
                print("Not logged in", file=sys.stderr)
                return 1
            out(args, profile, f"@{profile.username} ({profile.nickname}) id {profile.id}")
            return 0
        if args.command == "logout":
            await sock.logout()
            print("Logged out")
            return 0
        if args.command == "post":
            if args.kind == "video":
                result = await sock.post_video(args.file, args.caption, sound=args.sound, auto_sound=args.auto_sound,
                                               dry_run=args.dry_run)
            else:
                result = await sock.post_photos(args.files, args.caption, title=args.title, sound=args.sound,
                                                auto_sound=args.auto_sound, dry_run=args.dry_run)
            out(args, result, f"Posted {result.url or '(link not found yet)'} sound: {result.sound or 'none'}"
                if not args.dry_run else f"Dry run ok, sound: {result.sound or 'none'}")
            return 0
        if args.command == "chats":
            rows = await sock.chats()
            out(args, rows, "\n".join(f"{c.id}  {c.name}  {c.date}  {c.preview}" for c in rows) or "No chats")
            return 0
        if args.command == "messages":
            rows = await sock.messages(args.chat_id)
            out(args, rows, "\n".join(f"{'me' if m.from_me else 'them'} [{m.kind}] {m.text or m.image or m.thumb}"
                                      for m in rows) or "No messages")
            return 0
        if args.command == "send":
            result = await sock.send_message(args.chat_id, args.text, args.client_id)
            out(args, result, f"Sent, id {result.id}" + (" (waiting for TikTok)" if result.pending else ""))
            return 0
        if await run_web_command(args, sock):
            return 0
        if args.command == "listen":
            def show(event):
                for message in event["messages"]:
                    if args.json:
                        print(json.dumps({"chat": dump(event["chat"]), "message": dump(message)}, ensure_ascii=False))
                    else:
                        print(f"{event['chat'].name}: {message.text or message.kind}")
            sock.on("messages.upsert", show)
            print("Listening for new messages, Ctrl+C to stop", file=sys.stderr)
            await sock.start_listening(args.interval, args.history)
            return 0
    except TikSocketError as exc:
        print(f"error: {exc.code}: {exc}", file=sys.stderr)
        return 2
    finally:
        await sock.close()
        await page.close()
    return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
