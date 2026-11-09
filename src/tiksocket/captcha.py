from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import asdict, dataclass

from playwright.async_api import Page

from .errors import BadInput, CaptchaRequired, NotFound

log = logging.getLogger("tiksocket")

SELECTORS = ("#captcha-verify-container", "#captcha_container", ".captcha_verify_container",
             ".captcha-verify-container", "[id*=captcha-verify]", "[class*=captcha_verify]",
             "iframe[src*=captcha]", "iframe[id*=captcha]")
WORDS = r"drag the slider|fit the puzzle|select \d+ objects|verify to continue|rotate the|complete the puzzle|" \
        r"drag the puzzle|select the objects|choose the"
TEXT = re.compile(WORDS, re.I)
REFRESH = ("[class*=captcha] [class*=refresh]", "[id*=captcha] [class*=refresh]", "[aria-label*=refresh i]",
           ".secsdk_captcha_refresh", "[data-testid*=refresh]")
DETECT_JS = r"""([selectors, words]) => {
  const pattern = new RegExp(words, 'i');
  const shown = (e) => {
    const r = e.getBoundingClientRect();
    const s = getComputedStyle(e);
    return r.width > 40 && r.height > 40 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const title = (e) => ((e.innerText || '').trim().split('\n')[0] || '').slice(0, 120);
  for (const selector of selectors) {
    for (const e of document.querySelectorAll(selector)) {
      if (shown(e)) return {found: true, title: title(e), kind: kindOf(e)};
    }
  }
  const boxes = document.querySelectorAll('[role=dialog], .TUXModal, [class*=Modal], [class*=modal]');
  for (const e of boxes) {
    if (shown(e) && pattern.test(e.innerText || '')) return {found: true, title: title(e), kind: kindOf(e)};
  }
  return {found: false};
  function kindOf(e) {
    const text = (e.innerText || '').toLowerCase();
    if (/slider|puzzle/.test(text)) return 'slide';
    if (/rotate/.test(text)) return 'rotate';
    if (/select|choose/.test(text)) return 'select';
    return 'other';
  }
}"""


@dataclass
class Challenge:
    id: str
    title: str = ""
    kind: str = "other"
    url: str = ""
    since: float = 0.0
    expires: float = 0.0
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


Emit = Callable[[str, object], Awaitable[None]]


def _norm(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise BadInput("coordinates are numbers between 0 and 1") from exc
    return min(1.0, max(0.0, number))


class CaptchaGate:
    def __init__(self, emit: Emit | None = None, timeout: float = 600.0):
        self.emit = emit
        self.timeout = timeout
        self.page: Page | None = None
        self.challenge: Challenge | None = None
        self._turn = asyncio.Lock()

    @property
    def active(self) -> bool:
        return self.challenge is not None and self.page is not None and not self.page.is_closed()

    async def detect(self, page: Page | None) -> dict | None:
        if page is None or page.is_closed():
            return None
        try:
            found = await page.evaluate(DETECT_JS, [list(SELECTORS), WORDS])
        except Exception:
            return None
        return found if isinstance(found, dict) and found.get("found") else None

    async def _say(self, event: str, data) -> None:
        if self.emit is None:
            return
        try:
            await self.emit(event, data)
        except Exception:
            log.exception("captcha event handler failed")

    async def hold(self, page: Page | None) -> bool:
        found = await self.detect(page)
        if not found:
            return False
        if self.timeout <= 0:
            raise CaptchaRequired(f"TikTok asked for a captcha: {found.get('title') or 'verify'}")
        async with self._turn:
            found = await self.detect(page)
            if not found:
                return False
            now = time.time()
            size = page.viewport_size or {"width": 0, "height": 0}
            self.page = page
            self.challenge = Challenge(id=secrets.token_hex(6), title=found.get("title") or "",
                                       kind=found.get("kind") or "other", url=page.url, since=now,
                                       expires=now + self.timeout, width=size["width"], height=size["height"])
            log.warning("captcha on %s, waiting up to %ss for a person", page.url, int(self.timeout))
            await self._say("captcha.required", self.challenge)
            try:
                gone = 0
                while time.time() < self.challenge.expires:
                    await asyncio.sleep(1.5)
                    if page.is_closed():
                        break
                    gone = gone + 1 if not await self.detect(page) else 0
                    if gone >= 2:
                        await self._say("captcha.solved", self.challenge)
                        await page.wait_for_timeout(1500)
                        return True
                await self._say("captcha.failed", self.challenge)
                raise CaptchaRequired("TikTok asked for a captcha and it was not solved in time")
            finally:
                self.page, self.challenge = None, None

    def _live(self) -> Page:
        if not self.active:
            raise NotFound("no captcha is waiting")
        return self.page

    async def image(self, quality: int = 75) -> bytes:
        return await self._live().screenshot(type="jpeg", quality=quality, timeout=10000)

    def _point(self, x, y) -> tuple[float, float]:
        page = self._live()
        size = page.viewport_size or {"width": 1, "height": 1}
        return _norm(x) * size["width"], _norm(y) * size["height"]

    async def tap(self, x, y) -> None:
        page = self._live()
        px, py = self._point(x, y)
        await page.mouse.click(px, py)

    async def drag(self, path: Iterable) -> None:
        page = self._live()
        points = []
        for item in path or []:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                raise BadInput("path is a list of [x, y, ms] points")
            px, py = self._point(item[0], item[1])
            wait = max(0.0, min(float(item[2]) if len(item) > 2 else 16.0, 400.0))
            points.append((px, py, wait))
        if len(points) < 2:
            raise BadInput("a drag needs at least two points")
        await page.mouse.move(points[0][0], points[0][1])
        await page.mouse.down()
        for px, py, wait in points[1:]:
            await page.wait_for_timeout(wait)
            await page.mouse.move(px, py)
        await page.wait_for_timeout(120)
        await page.mouse.up()

    async def refresh(self) -> bool:
        page = self._live()
        for selector in REFRESH:
            try:
                found = page.locator(selector).first
                if await found.count() and await found.is_visible():
                    await found.click(timeout=3000)
                    return True
            except Exception:
                continue
        return False
