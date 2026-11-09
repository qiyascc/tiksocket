from __future__ import annotations

import asyncio
import logging
import os
import socket
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
    persistent: bool = True
    args: list[str] = field(default_factory=lambda: ["--disable-blink-features=AutomationControlled", "--no-sandbox"])


class BrowserHost:
    def __init__(self, options: BrowserOptions | None = None):
        self.options = options or BrowserOptions()
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()
        self._profiles: dict[str, BrowserContext] = {}
        self._version = ""

    async def _playwright(self) -> Playwright:
        if self._pw is None:
            self._pw = await async_playwright().start()
        return self._pw

    def _launch(self) -> dict:
        launch = {"headless": self.options.headless, "args": list(self.options.args)}
        if self.options.proxy:
            launch["proxy"] = {"server": self.options.proxy}
        if self.options.executable_path:
            launch["executable_path"] = self.options.executable_path
        return launch

    def _settings(self, version: str) -> dict:
        return {"viewport": dict(self.options.viewport), "locale": self.options.locale,
                "timezone_id": self.options.timezone,
                "user_agent": self.options.user_agent or matching_agent(version)}

    async def browser(self) -> Browser:
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            pw = await self._playwright()
            self._browser = await pw.chromium.launch(**self._launch())
            self._version = self._browser.version
            log.info("browser ready (headless=%s)", self.options.headless)
            return self._browser

    async def context(self, state: dict | None = None, profile: str | Path | None = None) -> BrowserContext:
        if profile is not None and self.options.persistent:
            return await self._profile(Path(profile), state)
        browser = await self.browser()
        settings = self._settings(browser.version)
        if state:
            settings["storage_state"] = state
        return await browser.new_context(**settings)

    async def _profile(self, folder: Path, state: dict | None) -> BrowserContext:
        key = str(folder.resolve())
        async with self._lock:
            context = self._profiles.get(key)
            if context is not None and _alive(context):
                return context
            folder.mkdir(parents=True, exist_ok=True)
            _unlock(folder)
            pw = await self._playwright()
            if not self._version:
                probe = await pw.chromium.launch(**self._launch())
                self._version = probe.version
                await probe.close()
            context = await pw.chromium.launch_persistent_context(str(folder), **self._launch(),
                                                                  **self._settings(self._version))
            if state and state.get("cookies"):
                try:
                    await context.add_cookies(state["cookies"])
                except Exception:
                    log.warning("could not seed cookies into the browser profile")
            self._profiles[key] = context

            def forget(_=None, key=key, context=context) -> None:
                if self._profiles.get(key) is context:
                    self._profiles.pop(key, None)

            context.on("close", forget)
            log.info("browser profile ready %s", folder.name)
            return context

    def shared(self, context: BrowserContext | None) -> bool:
        return context is not None and any(context is c for c in self._profiles.values())

    async def release(self, context: BrowserContext | None, *pages: Page | None) -> None:
        if context is None:
            return
        if not self.shared(context):
            try:
                await context.close()
            except Exception:
                pass
            return
        for page in pages:
            if page is not None and not page.is_closed():
                try:
                    await page.close()
                except Exception:
                    pass

    async def drop(self, profile: str | Path) -> None:
        key = str(Path(profile).resolve())
        context = self._profiles.pop(key, None)
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass

    async def close(self) -> None:
        for context in list(self._profiles.values()):
            try:
                await context.close()
            except Exception:
                pass
        self._profiles.clear()
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._pw is not None:
            await self._pw.stop()
        self._browser, self._pw = None, None


def _unlock(folder: Path) -> None:
    lock = folder / "SingletonLock"
    try:
        owner = os.readlink(lock)
    except OSError:
        return
    host, _, pid = owner.rpartition("-")
    if host and host != socket.gethostname():
        return
    try:
        os.kill(int(pid), 0)
        return
    except (ValueError, ProcessLookupError):
        pass
    except PermissionError:
        return
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            (folder / name).unlink()
        except OSError:
            pass
    log.info("removed a stale browser profile lock in %s", folder)


def _alive(context: BrowserContext) -> bool:
    try:
        browser = context.browser
        return browser is None or browser.is_connected()
    except Exception:
        return False


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
