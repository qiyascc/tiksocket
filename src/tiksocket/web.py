from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse

from playwright.async_api import BrowserContext, Page, Response

from . import human, webparse
from .auth import AuthState
from .browser import BrowserHost, body_text, snapshot
from .captcha import CaptchaGate
from .constants import HOME
from .errors import (
    ActionFailed,
    CaptchaRequired,
    LoggedOut,
    NotConnected,
    NotFound,
    PageChanged,
    PrivateAccount,
    RateLimited,
    TikSocketError,
    Unavailable,
)

log = logging.getLogger("tiksocket")
TRIES = 3
KEEP = {"WebIdLastTime", "aid", "app_language", "app_name", "browser_language", "browser_name", "browser_online",
        "browser_platform", "browser_version", "channel", "cookie_enabled", "data_collection_enabled", "device_id",
        "device_platform", "focus_state", "history_len", "is_fullscreen", "is_page_visible", "language", "odinId", "os",
        "priority_region", "region", "screen_height", "screen_width", "tz_name", "user_is_login", "verifyFp",
        "webcast_language"}
BASE = {"aid": "1988", "app_name": "tiktok_web", "device_platform": "web_pc", "app_language": "en", "language": "en",
        "channel": "tiktok_web", "cookie_enabled": "true", "browser_online": "true", "browser_name": "Mozilla",
        "user_is_login": "true", "is_page_visible": "true", "focus_state": "true", "is_fullscreen": "false", "os": "windows"}
XHR_JS = """async ([url, method, body, headers]) => {
  return await new Promise((done) => {
    const x = new XMLHttpRequest();
    x.open(method, url);
    x.withCredentials = true;
    for (const [k, v] of Object.entries(headers || {})) x.setRequestHeader(k, v);
    x.onload = () => done([x.status, x.responseText]);
    x.onerror = () => done([0, '']);
    x.ontimeout = () => done([0, '']);
    x.timeout = 30000;
    x.send(body || null);
  });
}"""
UNIVERSAL_JS = """() => {
  const s = document.querySelector('#__UNIVERSAL_DATA_FOR_REHYDRATION__');
  if (!s) return null;
  try { return JSON.parse(s.textContent).__DEFAULT_SCOPE__ || null; } catch (e) { return null; }
}"""
CLOSERS = ("[data-e2e=modal-close-inner-button]", ".TUXModal-closeButton", "[role=dialog] button[aria-label=Close]",
           "[role=dialog] button[aria-label*=close i]", "[data-e2e=edit-profile-close]")
LATER = re.compile(r"^\s*(not now|maybe later|later|skip|got it|ok|close|dismiss)\s*$", re.I)
Matcher = str | Iterable[str]


def _paths(match: Matcher) -> tuple[str, ...]:
    return (match,) if isinstance(match, str) else tuple(match)


class WebSession:
    def __init__(self, host: BrowserHost, auth: AuthState, gate: CaptchaGate | None = None):
        self.host = host
        self.auth = auth
        self.gate = gate or CaptchaGate(timeout=0)
        self.context: BrowserContext | None = None
        self._page: Page | None = None
        self.tab: Page | None = None
        self.lock = asyncio.Lock()
        self.params: dict[str, str] = {}

    async def page(self) -> Page:
        if self._page is not None and not self._page.is_closed():
            return self._page
        state = self.auth.load_state()
        if state is None:
            raise NotConnected("log in first")
        self.context = await self.host.context(state, self.auth.browser_folder())
        self._page = await self.context.new_page()
        self._page.on("request", self._learn)
        await self._load(self._page, HOME, 4000)
        return self._page

    @property
    def view(self) -> Page | None:
        return self.tab if self.tab is not None and not self.tab.is_closed() else self._page

    def _learn(self, request) -> None:
        if self.params.get("device_id") or "/api/" not in request.url or "device_id=" not in request.url:
            return
        query = dict(parse_qsl(urlparse(request.url).query))
        self.params = {k: v for k, v in query.items() if k in KEEP}

    async def goto(self, url: str, settle: int = 3500) -> Page:
        await self.page()
        if self.tab is not None and not self.tab.is_closed():
            try:
                await self.tab.close()
            except Exception:
                pass
        self.tab = await self.context.new_page()
        return await self._load(self.tab, url, settle)

    async def _load(self, page: Page, url: str, settle: int) -> Page:
        delay = 2
        refused = 0
        for attempt in range(TRIES):
            try:
                response = await page.goto(url, wait_until="load", timeout=60000)
                if response is not None and response.status in (403, 429):
                    refused += 1
                    log.warning("TikTok refused %s with %s (try %s)", urlparse(url).path, response.status, attempt + 1)
                    await asyncio.sleep(delay * 2)
                    delay *= 2
                    continue
                if response is not None and response.status == 404:
                    raise NotFound(f"TikTok has no page at {urlparse(url).path}")
                await page.wait_for_timeout(settle)
                await human.read(page)
                await self.gate.hold(page)
                await self.check()
                await self.dismiss()
                return page
            except TikSocketError:
                raise
            except Exception as exc:
                if "ERR_HTTP_RESPONSE_CODE_FAILURE" in str(exc):
                    refused += 1
                    log.warning("TikTok refused %s with an empty error page (try %s)", urlparse(url).path, attempt + 1)
                    await asyncio.sleep(delay * 2)
                    delay *= 2
                    continue
                log.warning("page load failed (try %s): %s", attempt + 1, type(exc).__name__)
                await asyncio.sleep(delay)
                delay *= 2
        await snapshot(page, self.auth.debug_folder(), "web-load-error.png")
        if refused:
            raise RateLimited("TikTok refused the page, wait a while before trying again")
        raise Unavailable(f"could not open {url}")

    async def check(self) -> None:
        page = self.view
        if page is None:
            return
        if "/login" in page.url:
            raise LoggedOut("TikTok session ended")
        if await self.gate.detect(page):
            raise CaptchaRequired("TikTok asked for a captcha")

    async def dismiss(self) -> None:
        page = self.view
        if page is None:
            return
        for _ in range(3):
            acted = False
            try:
                drawer = page.locator("[data-e2e=inbox-notifications]")
                if await drawer.count() and await drawer.first.is_visible():
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(400)
                    if await drawer.first.is_visible():
                        await human.click(page.locator("[data-e2e=inbox-icon]").first, timeout=2000)
                        await page.wait_for_timeout(400)
                    acted = True
            except Exception:
                pass
            for selector in CLOSERS:
                try:
                    button = page.locator(selector).first
                    if await button.count() and await button.is_visible():
                        await human.click(button, timeout=1500)
                        await page.wait_for_timeout(400)
                        acted = True
                except Exception:
                    continue
            try:
                later = page.locator("[role=dialog] button, .TUXModal-overlay button").filter(has_text=LATER).first
                if await later.count() and await later.is_visible():
                    await human.click(later, timeout=1500)
                    acted = True
            except Exception:
                pass
            if not acted:
                return

    def _query(self, params: dict) -> str:
        page = self._page
        merged = {**BASE, **self.params, **{k: str(v) for k, v in params.items() if v is not None}}
        if page is not None:
            merged.setdefault("tz_name", "UTC")
        return urlencode(merged)

    async def api(self, path: str, params: dict | None = None, method: str = "GET", form: dict | None = None,
                  check: bool = True) -> dict:
        page = await self.page()
        url = f"https://www.tiktok.com{path}?{self._query(params or {})}"
        headers, body = {}, None
        if method != "GET":
            token = await self._csrf()
            headers = {"Content-Type": "application/x-www-form-urlencoded", "tt-csrf-token": token}
            body = urlencode(form or {})
        delay = 1.5
        last = ""
        for _ in range(TRIES):
            try:
                status, text = await page.evaluate(XHR_JS, [url, method, body, headers])
            except Exception as exc:
                status, text = 0, ""
                last = type(exc).__name__
            if status == 200 and text:
                try:
                    data = json.loads(text)
                except ValueError:
                    data = None
                if isinstance(data, dict):
                    if check:
                        self.raise_for(data)
                    return data
            last = last or f"http {status}"
            if status in (401, 403):
                break
            await asyncio.sleep(delay)
            delay *= 2
        raise Unavailable(f"TikTok did not answer {path} ({last or 'empty reply'})")

    async def _csrf(self) -> str:
        if self.context is None:
            return ""
        for cookie in await self.context.cookies(HOME):
            if cookie.get("name") == "tt_csrf_token":
                return str(cookie.get("value") or "")
        return ""

    def raise_for(self, data: dict) -> None:
        status, message = webparse.status_of(data)
        code = webparse.error_code(status, message)
        if not code:
            return
        text = message or f"TikTok status {status}"
        if code == "logged_out":
            raise LoggedOut(text)
        if code == "rate_limited":
            raise RateLimited(text)
        if code == "not_found":
            raise NotFound(text)
        if code == "private":
            raise PrivateAccount(text)
        raise ActionFailed(text)

    async def universal(self, url: str, key: str = "") -> dict:
        for _ in range(2):
            page = await self.goto(url, settle=2000)
            for _ in range(8):
                data = await page.evaluate(UNIVERSAL_JS)
                if data and (not key or data.get(key)):
                    return data
                await page.wait_for_timeout(1000)
        return {}

    async def collect(self, match: Matcher, action: Callable[[], Awaitable[None]], wait: float = 15.0,
                      until: Callable[[list[dict]], bool] | None = None) -> list[dict]:
        await self.page()
        paths = _paths(match)
        found: list[dict] = []
        pending: list[asyncio.Task] = []

        async def read(response: Response) -> None:
            try:
                data = await response.json()
            except Exception:
                return
            if isinstance(data, dict):
                found.append(data)

        def on_response(response: Response) -> None:
            if any(p in urlparse(response.url).path for p in paths):
                pending.append(asyncio.ensure_future(read(response)))

        self.context.on("response", on_response)
        try:
            await action()
            deadline = time.time() + wait
            while time.time() < deadline:
                await asyncio.sleep(0.4)
                if pending and all(t.done() for t in pending) and found and (until is None or until(found)):
                    break
        finally:
            self.context.remove_listener("response", on_response)
        return found

    async def expect(self, match: Matcher, action: Callable[[], Awaitable[None]], wait: float = 20.0,
                     method: str = "POST") -> dict:
        await self.page()
        paths = _paths(match)
        await human.before_action(self)
        for attempt in range(2):
            loop = asyncio.get_running_loop()
            future: asyncio.Future = loop.create_future()

            def on_response(response: Response, future=future) -> None:
                if future.done():
                    return
                if response.request.method.upper() == method and any(p in urlparse(response.url).path for p in paths):
                    future.set_result(response)

            self.context.on("response", on_response)
            try:
                await action()
                response = await asyncio.wait_for(future, wait)
            except TikSocketError:
                if attempt == 0 and await self.gate.hold(self.view):
                    continue
                raise
            except Exception as exc:
                if attempt == 0 and await self.gate.hold(self.view):
                    continue
                await snapshot(self.view, self.auth.debug_folder(), "web-action-error.png")
                raise ActionFailed("TikTok did not confirm the action") from exc
            finally:
                self.context.remove_listener("response", on_response)
            try:
                data = await response.json()
            except Exception:
                data = {}
            if response.status >= 400:
                raise ActionFailed(f"TikTok answered {response.status}")
            self.raise_for(data if isinstance(data, dict) else {})
            return data if isinstance(data, dict) else {}
        raise ActionFailed("TikTok did not confirm the action")

    async def find(self, selectors: Iterable[str], timeout: float = 8.0, text: re.Pattern | None = None):
        await self.page()
        page = self.view
        deadline = time.time() + timeout
        while time.time() < deadline:
            for selector in selectors:
                try:
                    found = page.locator(selector)
                    if text is not None:
                        found = found.filter(has_text=text)
                    count = await found.count()
                    for index in range(min(count, 6)):
                        item = found.nth(index)
                        if await item.is_visible():
                            return item
                except Exception:
                    continue
            await page.wait_for_timeout(400)
        return None

    async def press(self, selectors: Iterable[str], timeout: float = 8.0, text: re.Pattern | None = None) -> None:
        await self.page()
        page = self.view
        selectors = tuple(selectors)
        for attempt in range(TRIES):
            item = await self.find(selectors, timeout if attempt == 0 else 3.0, text)
            if item is None:
                await self.dismiss()
                hidden = await self._attached(selectors, text)
                if hidden is not None and attempt == TRIES - 1:
                    try:
                        await hidden.evaluate("e => e.click()")
                        return
                    except Exception:
                        pass
                continue
            try:
                await item.scroll_into_view_if_needed(timeout=3000)
                await human.click(item, timeout=4000)
                return
            except Exception:
                await self.dismiss()
                try:
                    await item.evaluate("e => e.click()")
                    return
                except Exception:
                    await page.wait_for_timeout(800)
        await snapshot(page, self.auth.debug_folder(), "web-missing-button.png")
        raise PageChanged(f"button not found: {selectors[0]}")

    async def _attached(self, selectors: tuple, text: re.Pattern | None):
        page = self.view
        for selector in selectors:
            try:
                found = page.locator(selector)
                if text is not None:
                    found = found.filter(has_text=text)
                if await found.count():
                    return found.first
            except Exception:
                continue
        return None

    async def text(self) -> str:
        await self.page()
        return await body_text(self.view)

    async def save(self) -> None:
        if self.context is not None:
            try:
                self.auth.save_state(await self.context.storage_state())
            except Exception:
                pass

    async def close(self) -> None:
        if self.context is not None:
            await self.save()
            await self.host.release(self.context, self.tab, self._page)
        self.context, self._page, self.tab = None, None, None
