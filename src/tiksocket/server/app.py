from __future__ import annotations

import asyncio
import base64
import hmac
import json
import logging
import re
import secrets
from pathlib import Path

from aiohttp import WSMsgType, web

from ..auth import use_multi_file_auth_state
from ..browser import BrowserHost, BrowserOptions
from ..client import TikSocket
from ..constants import DEFAULT_PORT, PHOTO_MAX
from ..errors import BadInput, NotFound, TikSocketError
from ..terminal import qr_svg

log = logging.getLogger("tiksocket")
NAME = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
STATIC = Path(__file__).parent / "static"
MANAGER = web.AppKey("manager", object)
TOKEN = web.AppKey("token", str)


def payload(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return [payload(item) for item in value]
    if isinstance(value, dict):
        return {k: payload(v) for k, v in value.items()}
    return value


class Account:
    def __init__(self, name: str, sock: TikSocket):
        self.name = name
        self.sock = sock
        self.qr = None
        self.prompt = None
        self.status = ""
        self.login = "none"


class Manager:
    def __init__(self, home: Path, host: BrowserHost, timezone: str = "UTC", listen: bool = False):
        self.home = Path(home)
        self.host = host
        self.timezone = timezone
        self.listen = listen
        self.accounts: dict[str, Account] = {}
        self.streams: set[asyncio.Queue] = set()

    def names(self) -> list[str]:
        found = set(self.accounts)
        if self.home.exists():
            found |= {p.name for p in self.home.iterdir() if (p / "state.bin").exists()}
        return sorted(found)

    def get(self, name: str) -> Account:
        if not NAME.match(name or ""):
            raise BadInput("account names use letters, digits, dot, dash and underscore")
        account = self.accounts.get(name)
        if account is None:
            sock = TikSocket(use_multi_file_auth_state(self.home / name), browser=self.host, timezone=self.timezone)
            account = self.accounts[name] = Account(name, sock)
            self._wire(account)
            if self.listen and sock.auth.exists:
                sock.start_listening()
        return account

    def _wire(self, account: Account) -> None:
        sock = account.sock

        async def on_qr(qr):
            account.qr, account.prompt, account.login = qr, None, "qr"

        async def on_verify(prompt):
            account.prompt, account.login = prompt, "verify"

        async def on_status(status):
            account.status = status

        async def on_update(update):
            if update.get("connection") == "open":
                account.login, account.qr, account.prompt = "open", None, None
                if self.listen:
                    sock.start_listening()
            elif update.get("connection") == "close" and account.login != "open":
                account.login = "closed"

        sock.on("qr", on_qr)
        sock.on("verify", on_verify)
        sock.on("qr.status", on_status)
        sock.on("connection.update", on_update)

        async def relay(event, data):
            await self.publish(account.name, event, data)

        sock.on("*", relay)

    async def publish(self, name: str, event: str, data) -> None:
        if event in ("qr",):
            data = {"url": getattr(data, "url", ""), "has_image": getattr(data, "image", None) is not None}
        message = json.dumps({"account": name, "event": event, "data": payload(data)}, ensure_ascii=False, default=str)
        for queue in list(self.streams):
            if queue.qsize() < 200:
                queue.put_nowait(message)

    def login_view(self, account: Account) -> dict:
        view = {"state": account.login, "status": account.status, "profile": account.sock.profile.to_dict()
                if account.sock.auth.exists else None}
        if account.qr is not None and account.login == "qr":
            image = _data_url(account.qr.image, "image/png")
            if not image and account.qr.url:
                image = _data_url(qr_svg(account.qr.url), "image/svg+xml")
            view["qr"] = {"url": account.qr.url, "image": image}
        if account.prompt is not None and account.login == "verify":
            view["prompt"] = account.prompt.to_dict()
        return view

    async def close(self) -> None:
        for account in self.accounts.values():
            await account.sock.close()
        await self.host.close()


def _data_url(blob: bytes | None, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(blob).decode()}" if blob else ""


@web.middleware
async def guard(request: web.Request, handler):
    if request.path.startswith("/api/"):
        token = request.app[TOKEN]
        given = request.headers.get("Authorization", "").removeprefix("Bearer ").strip() or request.query.get("token", "")
        if token and not hmac.compare_digest(given, token):
            return web.json_response({"error": "unauthorized"}, status=401)
    try:
        return await handler(request)
    except TikSocketError as exc:
        return web.json_response(exc.to_dict(), status=exc.status)
    except (ValueError, json.JSONDecodeError) as exc:
        return web.json_response({"error": "bad_input", "message": str(exc)}, status=400)


def _account(request: web.Request) -> Account:
    return request.app[MANAGER].get(request.match_info["name"])


async def _body(request: web.Request) -> dict:
    if not request.can_read_body:
        return {}
    data = await request.json()
    if not isinstance(data, dict):
        raise BadInput("JSON object expected")
    return data


async def health(request):
    return web.json_response({"ok": True})


async def index(request):
    return web.FileResponse(STATIC / "index.html")


async def accounts(request):
    manager = request.app[MANAGER]
    rows = []
    for name in manager.names():
        auth = use_multi_file_auth_state(manager.home / name)
        rows.append({"account": name, "connected": auth.exists, "profile": auth.load_profile()})
    return web.json_response({"accounts": rows})


async def login_start(request):
    account = _account(request)
    account.login, account.prompt = "starting", None
    await account.sock.request_qr()
    return web.json_response(request.app[MANAGER].login_view(account))


async def login_state(request):
    return web.json_response(request.app[MANAGER].login_view(_account(request)))


async def login_code(request):
    data = await _body(request)
    await _account(request).sock.submit_code(str(data.get("code") or ""))
    await asyncio.sleep(2.5)
    return await login_state(request)


async def login_press(request):
    data = await _body(request)
    await _account(request).sock.press_button(int(data.get("index") or 0))
    await asyncio.sleep(2.5)
    return await login_state(request)


async def login_tap(request):
    data = await _body(request)
    sock = _account(request).sock
    if data.get("x2") is not None:
        await sock.drag(float(data["x"]), float(data["y"]), float(data["x2"]), float(data["y2"]))
    else:
        await sock.tap(float(data.get("x") or 0), float(data.get("y") or 0))
    await asyncio.sleep(1.5)
    prompt = await sock.verify_prompt()
    return web.json_response({"prompt": prompt.to_dict(), "screenshot": _data_url(prompt.screenshot, "image/jpeg")})


async def login_screenshot(request):
    prompt = await _account(request).sock.verify_prompt()
    if prompt.screenshot is None:
        raise NotFound("no screenshot for this step")
    return web.Response(body=prompt.screenshot, content_type="image/jpeg")


async def login_cookie(request):
    data = await _body(request)
    profile = await _account(request).sock.login_with_cookies(data.get("cookie") or "")
    return web.json_response({"profile": profile.to_dict()})


async def me(request):
    profile = await _account(request).sock.whoami(live=request.query.get("live") == "1")
    if profile is None:
        return web.json_response({"connected": False})
    return web.json_response({"connected": True, "profile": profile.to_dict()})


async def logout(request):
    await _account(request).sock.logout()
    return web.json_response({"ok": True})


async def post(request):
    sock = _account(request).sock
    reader = await request.multipart()
    fields, files = {}, []
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.filename:
            files.append(await part.read(decode=False))
            if len(files) > PHOTO_MAX:
                raise BadInput(f"at most {PHOTO_MAX} files")
        else:
            fields[part.name] = (await part.text()).strip()
    kind = fields.get("kind") or "video"
    options = {"sound": fields.get("sound", ""), "auto_sound": fields.get("auto_sound") in ("1", "true", "on"),
               "dry_run": fields.get("dry_run") in ("1", "true", "on")}
    if kind == "video":
        if len(files) != 1:
            raise BadInput("send exactly one video file")
        result = await sock.post_video(bytes(files[0]), fields.get("caption", ""), **options)
    else:
        result = await sock.post_photos([bytes(f) for f in files], fields.get("caption", ""),
                                        title=fields.get("title", ""), **options)
    return web.json_response(result.to_dict())


async def chats(request):
    rows = await _account(request).sock.chats()
    return web.json_response({"chats": payload(rows)})


async def messages(request):
    rows = await _account(request).sock.messages(request.match_info["chat"])
    return web.json_response({"messages": payload(rows)})


async def send(request):
    data = await _body(request)
    result = await _account(request).sock.send_message(request.match_info["chat"], str(data.get("text") or ""),
                                                       str(data.get("client_id") or "")[:64])
    return web.json_response(result.to_dict())


async def events(request):
    manager = request.app[MANAGER]
    wanted = request.query.get("account", "")
    queue: asyncio.Queue = asyncio.Queue()
    manager.streams.add(queue)
    response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache",
                                           "X-Accel-Buffering": "no"})
    await response.prepare(request)
    try:
        await response.write(b": connected\n\n")
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), 20)
            except asyncio.TimeoutError:
                await response.write(b": ping\n\n")
                continue
            if wanted and json.loads(message).get("account") != wanted:
                continue
            await response.write(f"data: {message}\n\n".encode())
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        manager.streams.discard(queue)
    return response


async def socket_events(request):
    manager = request.app[MANAGER]
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(request)
    queue: asyncio.Queue = asyncio.Queue()
    manager.streams.add(queue)

    async def pump():
        while True:
            await ws.send_str(await queue.get())

    task = asyncio.create_task(pump())
    try:
        async for message in ws:
            if message.type == WSMsgType.ERROR:
                break
    finally:
        task.cancel()
        manager.streams.discard(queue)
    return ws


def build_app(manager: Manager, token: str = "") -> web.Application:
    app = web.Application(middlewares=[guard], client_max_size=400 * 1024 * 1024)
    app[MANAGER] = manager
    app[TOKEN] = token

    async def cleanup(app):
        await manager.close()

    app.on_cleanup.append(cleanup)
    r = app.router
    r.add_get("/", index)
    r.add_get("/health", health)
    r.add_static("/static", STATIC)
    r.add_get("/api/accounts", accounts)
    base = "/api/accounts/{name}"
    r.add_post(f"{base}/login/qr", login_start)
    r.add_get(f"{base}/login", login_state)
    r.add_post(f"{base}/login/code", login_code)
    r.add_post(f"{base}/login/press", login_press)
    r.add_post(f"{base}/login/tap", login_tap)
    r.add_get(f"{base}/login/screenshot", login_screenshot)
    r.add_post(f"{base}/login/cookie", login_cookie)
    r.add_get(f"{base}/me", me)
    r.add_delete(f"{base}/session", logout)
    r.add_post(f"{base}/posts", post)
    r.add_get(f"{base}/chats", chats)
    r.add_get(f"{base}/chats/{{chat}}/messages", messages)
    r.add_post(f"{base}/chats/{{chat}}/messages", send)
    r.add_get("/api/events", events)
    r.add_get("/api/ws", socket_events)
    return app


async def run_server(home: Path, host: str = "127.0.0.1", port: int = DEFAULT_PORT, token: str = "",
                     listen: bool = False, headless: bool = True, proxy: str = "", timezone: str = "UTC") -> None:
    token = token or secrets.token_urlsafe(24)
    browser = BrowserHost(BrowserOptions(headless=headless, proxy=proxy, timezone=timezone))
    app = build_app(Manager(home, browser, timezone, listen), token)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    print(f"TikSocket running on http://{host}:{port}/?token={token}", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
