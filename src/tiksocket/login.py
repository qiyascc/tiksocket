from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable

from playwright.async_api import BrowserContext, Page

from .auth import AuthState
from .browser import BrowserHost, body_text, snapshot
from .constants import ACCOUNT_URL, HOME, LOGIN_TTL, LOGIN_URL, VIEWPORT
from .errors import BadInput, LoginExpired, NotConnected, Unavailable
from .js import COVERED_JS, DIALOG_JS
from .models import Profile, QRCode, VerifyPrompt

log = logging.getLogger("tiksocket")
Emit = Callable[[str, object], Awaitable[None]]
SUBMIT = re.compile(r"verify|confirm|submit|next|continue|log in|ok", re.I)


def has_session(cookies: list[dict]) -> bool:
    return any(c.get("name") in ("sessionid", "sessionid_ss") and c.get("value") for c in cookies)


def parse_cookies(raw) -> list[dict]:
    if isinstance(raw, list):
        items = [(str(c.get("name") or ""), str(c.get("value") or "")) for c in raw if isinstance(c, dict)]
    elif isinstance(raw, dict):
        items = [(str(k), str(v)) for k, v in raw.items()]
    else:
        text = str(raw or "").strip()
        if text.startswith("["):
            try:
                return parse_cookies(json.loads(text))
            except ValueError:
                return []
        if text.lower().startswith("cookie:"):
            text = text[7:]
        items = []
        for part in text.split(";"):
            name, sep, value = part.strip().partition("=")
            if sep and name:
                items.append((name.strip(), value.strip()))
    return [{"name": name, "value": value, "domain": ".tiktok.com", "path": "/", "secure": True, "httpOnly": False,
             "sameSite": "None"} for name, value in items if name and value and len(name) < 128 and len(value) < 4096]


async def fetch_profile(context: BrowserContext) -> Profile | None:
    try:
        response = await context.request.get(ACCOUNT_URL, timeout=20000)
        body = await response.json()
    except Exception:
        return None
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict) or not (data.get("username") or data.get("user_id_str") or data.get("user_id")):
        return None
    return Profile(id=str(data.get("user_id_str") or data.get("user_id") or ""), username=str(data.get("username") or ""),
                   nickname=str(data.get("screen_name") or ""), avatar=str(data.get("avatar_url") or ""))


def qr_from_payload(body) -> QRCode | None:
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return None
    url = str(data.get("qrcode_index_url") or "")
    image = None
    raw = data.get("qrcode")
    if isinstance(raw, str) and raw:
        try:
            image = base64.b64decode(raw.split(",", 1)[-1])
        except ValueError:
            image = None
    if not url and image is None:
        return None
    return QRCode(url=url, image=image, expires_in=LOGIN_TTL)


def qr_status(body) -> str:
    data = body.get("data") if isinstance(body, dict) else None
    status = str((data or {}).get("status") or "") if isinstance(data, dict) else ""
    return status if status in ("new", "scanned", "confirmed", "expired", "refused") else ""


def decode_image(image: bytes) -> str:
    try:
        import cv2
        import numpy
    except ImportError:
        return ""
    try:
        frame = cv2.imdecode(numpy.frombuffer(image, numpy.uint8), cv2.IMREAD_COLOR)
        text, _, _ = cv2.QRCodeDetector().detectAndDecode(frame)
        return text or ""
    except Exception:
        return ""


class QRLogin:
    def __init__(self, host: BrowserHost, auth: AuthState, emit: Emit, ttl: int = LOGIN_TTL):
        self.host = host
        self.auth = auth
        self.emit = emit
        self.ttl = ttl
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.qr: QRCode | None = None
        self.status = "new"
        self.prompt_sig = ""
        self.started = 0.0
        self.task: asyncio.Task | None = None
        self.done: asyncio.Future | None = None
        self._qr_event = asyncio.Event()

    async def start(self) -> QRCode:
        self.done = asyncio.get_running_loop().create_future()
        self.context = await self.host.context()
        self.page = await self.context.new_page()
        self.page.on("response", self._on_response)
        for attempt in range(3):
            try:
                await self.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
                break
            except Exception as exc:
                log.warning("login page failed (try %s): %s", attempt + 1, exc)
                await asyncio.sleep(2 * (attempt + 1))
        else:
            await self.close()
            raise Unavailable("TikTok login page did not load")
        self.started = time.time()
        try:
            await asyncio.wait_for(self._qr_event.wait(), 15)
        except asyncio.TimeoutError:
            self.qr = await self._canvas_qr()
        await self.emit("qr", self.qr)
        self.task = asyncio.create_task(self._watch())
        return self.qr

    def _on_response(self, response) -> None:
        url = response.url
        if "get_qrcode" in url or "check_qrconnect" in url:
            asyncio.ensure_future(self._read(response, "get_qrcode" in url))

    async def _read(self, response, is_qr: bool) -> None:
        try:
            body = await response.json()
        except Exception:
            return
        if is_qr:
            found = qr_from_payload(body)
            if found is None:
                return
            if not found.url and found.image:
                found.url = decode_image(found.image)
            fresh = self.qr is None or found.url != self.qr.url
            self.qr = found
            self._qr_event.set()
            if fresh and self.task is not None:
                await self.emit("qr", found)
            return
        status = qr_status(body)
        if status and status != self.status:
            self.status = status
            await self.emit("qr.status", status)

    async def _canvas_qr(self) -> QRCode:
        image = None
        try:
            canvas = self.page.locator("canvas").first
            await canvas.wait_for(state="visible", timeout=20000)
            image = await canvas.screenshot(timeout=10000)
        except Exception:
            image = await self.page.screenshot(timeout=10000)
        return QRCode(url=decode_image(image) if image else "", image=image, expires_in=self.ttl)

    async def covered(self) -> bool:
        try:
            return bool(await self.page.evaluate(COVERED_JS))
        except Exception:
            return False

    async def prompt(self) -> VerifyPrompt:
        try:
            found = await self.page.evaluate(DIALOG_JS) or {}
        except Exception:
            found = {}
        prompt = VerifyPrompt(title=found.get("title") or "", lines=found.get("lines") or [],
                              buttons=found.get("buttons") or [], inputs=found.get("inputs") or [],
                              captcha=bool(found.get("captcha")))
        if prompt.captcha or not (prompt.buttons or prompt.inputs or prompt.lines):
            prompt.screenshot = await self.page.screenshot(type="jpeg", quality=70, timeout=10000)
        return prompt

    async def _watch(self) -> None:
        try:
            while time.time() - self.started < self.ttl:
                await asyncio.sleep(2)
                cookies = await self.context.cookies(HOME)
                if has_session(cookies):
                    await asyncio.sleep(3)
                    profile = await fetch_profile(self.context) or Profile()
                    self.auth.save_state(await self.context.storage_state())
                    self.auth.save_profile(profile.to_dict())
                    if not self.done.done():
                        self.done.set_result(profile)
                    return
                if self.status == "expired":
                    await self._refresh()
                if await self.covered():
                    prompt = await self.prompt()
                    sig = json.dumps([prompt.title, prompt.lines, [b.get("label") for b in prompt.buttons]])
                    if sig != self.prompt_sig:
                        self.prompt_sig = sig
                        await self.emit("verify", prompt)
            if not self.done.done():
                self.done.set_exception(LoginExpired("QR code expired"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("qr login failed")
            await snapshot(self.page, self.auth.debug_folder(), "login-error.png")
            if not self.done.done():
                self.done.set_exception(Unavailable(str(exc)))
        finally:
            await self.close()

    async def _refresh(self) -> None:
        try:
            text = (await body_text(self.page)).lower()
            if "expired" in text or "refresh" in text:
                await self.page.get_by_text(re.compile(r"refresh", re.I)).first.click(timeout=3000)
                self.status = "new"
                await asyncio.sleep(1.5)
        except Exception:
            pass

    def _alive(self) -> Page:
        if self.page is None or self.page.is_closed():
            raise NotConnected("no login in progress")
        return self.page

    async def submit_code(self, code: str) -> None:
        page = self._alive()
        code = re.sub(r"\s+", "", code or "")[:12]
        if not code:
            raise BadInput("empty code")
        await page.evaluate(DIALOG_JS)
        boxes = page.locator("[data-ea-input]")
        count = await boxes.count()
        if count > 1:
            await boxes.first.click(timeout=5000)
            await page.keyboard.type(code, delay=90)
        elif count == 1:
            await boxes.first.fill(code, timeout=5000)
        else:
            await page.keyboard.type(code, delay=90)
        await page.wait_for_timeout(600)
        submit = page.locator("[data-ea-btn]").filter(has_text=SUBMIT)
        if await submit.count():
            await submit.first.click(timeout=5000)
        else:
            await page.keyboard.press("Enter")
        self.started = max(self.started, time.time() - self.ttl + 180)

    async def press(self, index: int) -> None:
        page = self._alive()
        await page.evaluate(DIALOG_JS)
        await page.locator(f'[data-ea-btn="{int(index)}"]').first.click(timeout=5000)
        self.started = max(self.started, time.time() - self.ttl + 180)

    async def tap(self, x: float, y: float) -> None:
        page = self._alive()
        await page.mouse.click(_clamp(x) * VIEWPORT["width"], _clamp(y) * VIEWPORT["height"])

    async def drag(self, x: float, y: float, x2: float, y2: float, steps: int = 18) -> None:
        page = self._alive()
        width, height = VIEWPORT["width"], VIEWPORT["height"]
        await page.mouse.move(_clamp(x) * width, _clamp(y) * height)
        await page.mouse.down()
        for i in range(1, steps + 1):
            await page.mouse.move((_clamp(x) + (_clamp(x2) - _clamp(x)) * i / steps) * width,
                                  (_clamp(y) + (_clamp(y2) - _clamp(y)) * i / steps) * height)
            await page.wait_for_timeout(25)
        await page.mouse.up()

    async def wait(self, timeout: float | None = None) -> Profile:
        return await asyncio.wait_for(asyncio.shield(self.done), timeout)

    async def close(self) -> None:
        if self.context is not None:
            try:
                await self.context.close()
            except Exception:
                pass
        self.context, self.page = None, None

    async def cancel(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
        await self.close()


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value or 0)))


async def cookie_login(host: BrowserHost, auth: AuthState, raw) -> Profile:
    cookies = parse_cookies(raw)
    if not has_session(cookies):
        raise BadInput("cookie string has no sessionid")
    context = await host.context()
    try:
        await context.add_cookies(cookies)
        profile = await fetch_profile(context)
        if profile is None:
            raise BadInput("TikTok did not accept these cookies")
        auth.save_state(await context.storage_state())
        auth.save_profile(profile.to_dict())
        return profile
    finally:
        await context.close()
