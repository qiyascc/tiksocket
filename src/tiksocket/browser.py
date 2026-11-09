from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from .constants import VIEWPORT

log = logging.getLogger("tiksocket")
PLATFORMS = {"linux": "X11; Linux x86_64", "darwin": "Macintosh; Intel Mac OS X 10_15_7",
             "win32": "Windows NT 10.0; Win64; x64"}


def matching_agent(version: str, platform: str | None = None) -> str:
    major = (version or "131").split(".")[0]
    system = PLATFORMS.get(platform or sys.platform, PLATFORMS["linux"])
    return f"Mozilla/5.0 ({system}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"


@dataclass
class BrowserOptions:
    headless: bool = True
    proxy: str = ""
    user_agent: str = ""
    locale: str = "en-US"
    timezone: str = "UTC"
    viewport: dict = field(default_factory=lambda: dict(VIEWPORT))
    executable_path: str = ""
    args: list[str] = field(default_factory=lambda: ["--disable-blink-features=AutomationControlled", "--no-sandbox"])


class BrowserHost:
    def __init__(self, options: BrowserOptions | None = None):
        self.options = options or BrowserOptions()
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

    async def browser(self) -> Browser:
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            if self._pw is None:
                self._pw = await async_playwright().start()
            launch = {"headless": self.options.headless, "args": list(self.options.args)}
            if self.options.proxy:
                launch["proxy"] = {"server": self.options.proxy}
            if self.options.executable_path:
                launch["executable_path"] = self.options.executable_path
            self._browser = await self._pw.chromium.launch(**launch)
            log.info("browser ready (headless=%s)", self.options.headless)
            return self._browser

    async def context(self, state: dict | None = None) -> BrowserContext:
        browser = await self.browser()
        agent = self.options.user_agent or matching_agent(browser.version)
        settings = {"viewport": dict(self.options.viewport), "locale": self.options.locale,
                    "timezone_id": self.options.timezone, "user_agent": agent}
        if state:
            settings["storage_state"] = state
        return await browser.new_context(**settings)

    async def close(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._pw is not None:
            await self._pw.stop()
        self._browser, self._pw = None, None


async def snapshot(page: Page | None, folder: Path | None, name: str) -> Path | None:
    if page is None or folder is None:
        return None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        await page.screenshot(path=str(path), full_page=True, timeout=10000)
        return path
    except Exception:
        return None


async def body_text(page: Page) -> str:
    try:
        return (await page.locator("body").inner_text(timeout=5000)) or ""
    except Exception:
        return ""
