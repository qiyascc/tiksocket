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

    serve = sub.add_parser("serve", help="run the web UI and REST API")
    serve.add_argument("--host", default=os.environ.get("TIKSOCKET_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("TIKSOCKET_PORT") or DEFAULT_PORT))
    serve.add_argument("--token", default=os.environ.get("TIKSOCKET_TOKEN", ""), help="API token, generated if empty")
    serve.add_argument("--listen", action="store_true", help="poll messages of every logged in account")
    return parser


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
    return TikSocket(auth, headless=not args.show_browser, proxy=args.proxy, timezone=args.timezone)


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
