from __future__ import annotations

import hmac
import json
import logging
import secrets
import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path

from aiohttp import web

from ..errors import BadInput, TikSocketError

log = logging.getLogger("tiksocket")
STATIC = Path(__file__).parent / "static"
RESOLVE = web.AppKey("captcha_resolve", object)


def _sock(request: web.Request):
    return request.app[RESOLVE](request)


async def _json(request: web.Request) -> dict:
    if not request.can_read_body:
        return {}
    data = await request.json()
    if not isinstance(data, dict):
        raise BadInput("JSON object expected")
    return data


async def captcha_state(request: web.Request):
    challenge = _sock(request).pending_captcha
    return web.json_response({"pending": challenge.to_dict() if challenge else None})


async def captcha_image(request: web.Request):
    image = await _sock(request).captcha_image()
    return web.Response(body=image, content_type="image/jpeg", headers={"Cache-Control": "no-store"})


async def captcha_tap(request: web.Request):
    data = await _json(request)
    await _sock(request).captcha_tap(data.get("x"), data.get("y"))
    return web.json_response({"ok": True})


async def captcha_drag(request: web.Request):
    data = await _json(request)
    await _sock(request).captcha_drag(data.get("path") or [])
    return web.json_response({"ok": True})


async def captcha_refresh(request: web.Request):
    return web.json_response({"ok": await _sock(request).captcha_refresh()})


def add_routes(router: web.UrlDispatcher, base: str) -> None:
    router.add_get(f"{base}/captcha", captcha_state)
    router.add_get(f"{base}/captcha/image", captcha_image)
    router.add_post(f"{base}/captcha/tap", captcha_tap)
    router.add_post(f"{base}/captcha/drag", captcha_drag)
    router.add_post(f"{base}/captcha/refresh", captcha_refresh)


class CaptchaPage:
    def __init__(self, sock, host: str = "127.0.0.1", port: int = 8788, open_browser: bool = True,
                 out: Callable[[str], None] | None = None):
        self.sock = sock
        self.host = host
        self.port = port
        self.open_browser = open_browser
        self.out = out or (lambda text: print(text, file=sys.stderr, flush=True))
        self.token = secrets.token_urlsafe(18)
        self.runner: web.AppRunner | None = None

    @property
    def url(self) -> str:
        shown = "127.0.0.1" if self.host in ("0.0.0.0", "::") else self.host
        return f"http://{shown}:{self.port}/?token={self.token}"

    def _app(self) -> web.Application:
        token = self.token

        @web.middleware
        async def guard(request: web.Request, handler):
            given = request.headers.get("Authorization", "").removeprefix("Bearer ").strip() or \
                request.query.get("token", "")
            if request.path.startswith("/api/") and not hmac.compare_digest(given, token):
                return web.json_response({"error": "unauthorized"}, status=401)
            try:
                return await handler(request)
            except TikSocketError as exc:
                return web.json_response(exc.to_dict(), status=exc.status)
            except (ValueError, json.JSONDecodeError) as exc:
                return web.json_response({"error": "bad_input", "message": str(exc)}, status=400)

        async def page(request: web.Request):
            return web.FileResponse(STATIC / "captcha.html")

        app = web.Application(middlewares=[guard])
        app[RESOLVE] = lambda request: self.sock
        app.router.add_get("/", page)
        app.router.add_static("/static", STATIC)
        add_routes(app.router, "/api")
        return app

    async def start(self) -> None:
        if self.runner is not None:
            return
        self.runner = web.AppRunner(self._app())
        await self.runner.setup()
        await web.TCPSite(self.runner, self.host, self.port).start()

    async def on_required(self, challenge) -> None:
        try:
            await self.start()
        except OSError as exc:
            self.out(f"captcha: TikTok wants a captcha but port {self.port} is busy ({exc}). "
                     f"Use --captcha-port to pick another.")
            return
        title = getattr(challenge, "title", "") or "TikTok verification"
        minutes = max(1, int((getattr(challenge, "expires", 0) - getattr(challenge, "since", 0)) // 60))
        self.out("")
        self.out(f"TikTok asked for a captcha: {title}")
        self.out(f"Solve it here within {minutes} min, the command continues on its own:")
        self.out(f"  {self.url}")
        if self.host in ("127.0.0.1", "localhost"):
            self.out(f"  remote machine? run: ssh -L {self.port}:127.0.0.1:{self.port} <server>, then open the link")
        if self.open_browser:
            try:
                webbrowser.open(self.url, new=2)
            except Exception:
                pass

    async def on_solved(self, challenge) -> None:
        self.out("captcha solved, continuing")

    async def on_failed(self, challenge) -> None:
        self.out("captcha was not solved in time")

    def attach(self) -> CaptchaPage:
        self.sock.on("captcha.required", self.on_required)
        self.sock.on("captcha.solved", self.on_solved)
        self.sock.on("captcha.failed", self.on_failed)
        return self

    async def close(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None
