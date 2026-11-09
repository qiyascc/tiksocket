from __future__ import annotations

import logging
import re
import time

from playwright.async_api import Page

from . import labels
from .constants import CONTENT_URL, UPLOAD_URL
from .errors import BadMedia, CaptchaRequired, LoggedOut, PageChanged, PublishFailed, TikSocketError, Unavailable
from .js import PRESS_JS

log = logging.getLogger("tiksocket")


class Uploader:
    def __init__(self, page: Page):
        self.page = page
        self.api_ok = False
        self.api_fail = ""
        self.sound = ""

    async def open(self) -> None:
        page = self.page
        for attempt in range(3):
            try:
                await page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
                await page.wait_for_timeout(2500)
                await self.check_page()
                await page.locator('input[type="file"]').first.wait_for(state="attached", timeout=60000)
                return
            except TikSocketError:
                raise
            except Exception as exc:
                log.warning("upload page load failed (try %s): %s", attempt + 1, exc)
                await page.wait_for_timeout(3000 * (attempt + 1))
        raise Unavailable("TikTok upload page did not load")

    async def photo_input(self):
        page = self.page
        images = page.locator('input[type="file"][accept*="image"]')
        for _attempt in range(4):
            await self.dismiss()
            if await images.count():
                return images.first
            tab = page.get_by_role("tab", name=labels.exact("photos")).first
            if not await tab.count():
                tab = page.get_by_text(labels.exact("photos")).first
            try:
                await tab.click(timeout=5000)
            except Exception:
                pass
            try:
                await images.first.wait_for(state="attached", timeout=8000)
                return images.first
            except Exception:
                await page.wait_for_timeout(1500)
        raise PageChanged("TikTok upload page changed")

    async def run(self, paths, caption: str, mode: str = "video", title: str = "", sound_mode: str = "none",
                  sound: str = "", dry_run: bool = False) -> dict:
        page = self.page
        paths = [paths] if isinstance(paths, str) else list(paths)
        await self.open()
        if mode == "photo":
            file_input = await self.photo_input()
        else:
            file_input = page.locator('input[type="file"][accept*="video"]').first
            if not await file_input.count():
                file_input = page.locator('input[type="file"]').first
        try:
            await file_input.set_input_files(paths)
        except Exception as exc:
            await self.check_page()
            raise PageChanged("TikTok upload page changed") from exc
        await self.wait_ready()
        if title:
            await self.set_title(title)
        await self.set_caption(caption)
        if sound_mode in ("auto", "search"):
            self.sound = await self.add_sound(sound if sound_mode == "search" else "")
        await self.content_check_off()
        if dry_run:
            return {"ok": True, "id": "", "kind": mode, "url": "", "sound": self.sound}
        page.on("response", self.on_response)
        try:
            await self.click_publish()
            ok = await self.confirm()
        finally:
            page.remove_listener("response", self.on_response)
        if not ok:
            raise PublishFailed("TikTok did not confirm the post")
        return await self.find_post()

    async def check_page(self) -> None:
        url = self.page.url.lower()
        if "/login" in url:
            raise LoggedOut("TikTok session ended")
        try:
            captcha = await self.page.locator("#captcha-verify-container, #captcha_container, [class*='captcha' i]").count()
        except Exception:
            captcha = 0
        if captcha:
            raise CaptchaRequired("TikTok asked for a captcha")

    async def wait_ready(self) -> None:
        page = self.page
        editor = page.locator('div[contenteditable="true"]').first
        try:
            await editor.wait_for(state="visible", timeout=180000)
        except Exception as exc:
            await self.check_page()
            raise PageChanged("TikTok upload page changed") from exc
        deadline = time.time() + 600
        while time.time() < deadline:
            text = await self.body_text()
            if labels.matches(text, "failed_upload"):
                raise BadMedia("TikTok rejected the file")
            busy = re.search(r"\b(uploading|processing)\b|\b\d{1,2}(\.\d+)?\s?%", text, re.I)
            if not busy:
                break
            await page.wait_for_timeout(2000)
        await page.wait_for_timeout(3000)

    async def set_title(self, title: str) -> None:
        page = self.page
        field = page.locator('input[placeholder*="title" i], input[maxlength="90"], textarea[maxlength="90"]').first
        try:
            if not await field.count():
                return
            await field.click(timeout=5000)
            await field.fill(title, timeout=5000)
            if (await field.input_value()).strip() != title.strip():
                await field.fill("")
                await page.keyboard.type(title, delay=15)
        except Exception as exc:
            log.warning("tiktok title not set: %s", exc)

    async def add_sound(self, query: str) -> str:
        page = self.page
        for attempt in range(2):
            try:
                await self.dismiss()
                opener = page.get_by_role("button", name=labels.pattern("add_sound")).first
                if not await opener.count():
                    opener = page.get_by_text(labels.pattern("add_sound")).first
                if not await opener.count():
                    return ""
                await opener.scroll_into_view_if_needed(timeout=5000)
                await opener.click(timeout=5000)
                dialog = page.locator("[role=dialog], [class*=modal i]").filter(has=page.get_by_role("button", name=labels.exact("use"))).last
                await dialog.wait_for(state="visible", timeout=20000)
                if query:
                    search = dialog.locator("input").first
                    await search.fill(query, timeout=5000)
                    await search.press("Enter")
                    await page.wait_for_timeout(1500)
                    deadline = time.time() + 15
                    while time.time() < deadline:
                        text = (await dialog.inner_text(timeout=3000)).lower()
                        if query.lower().split()[0] in text or "no results" in text:
                            break
                        await page.wait_for_timeout(800)
                uses = dialog.get_by_role("button", name=labels.exact("use"))
                if not await uses.count():
                    await page.keyboard.press("Escape")
                    return ""
                first = uses.first
                row = first.locator("xpath=ancestor::*[.//img][1]")
                name = ""
                try:
                    name = ((await row.inner_text(timeout=3000)) or "").split("\n")[0].strip()
                except Exception:
                    pass
                await first.click(timeout=5000)
                try:
                    await dialog.wait_for(state="hidden", timeout=10000)
                except Exception:
                    await page.keyboard.press("Escape")
                await page.wait_for_timeout(1200)
                if name and name.lower() not in (await self.body_text()).lower():
                    log.warning("tiktok sound %r not visible after pick", name)
                return name
            except Exception as exc:
                log.warning("tiktok sound pick failed (try %s): %s", attempt + 1, exc)
                try:
                    await page.keyboard.press("Escape")
                except Exception:
                    pass
                await page.wait_for_timeout(1500)
        return ""

    async def body_text(self) -> str:
        try:
            return (await self.page.locator("body").inner_text(timeout=5000)) or ""
        except Exception:
            return ""

    async def set_caption(self, caption: str) -> None:
        if not caption:
            return
        page = self.page
        target = page.locator('div[contenteditable="true"]').first
        try:
            await target.click(timeout=8000)
        except Exception as exc:
            raise PageChanged("TikTok upload page changed") from exc
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Delete")
        lines = caption.replace("\r", "").split("\n")
        for index, line in enumerate(lines):
            if index:
                await page.keyboard.press("Escape")
                await page.keyboard.press("Shift+Enter")
            if line:
                await page.keyboard.type(line, delay=12)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(600)

    async def content_check_off(self) -> None:
        page = self.page
        section = page.locator("section, div, li, form").filter(has_text=labels.pattern("content_check")).first
        try:
            if await section.count() == 0:
                return
        except Exception:
            return
        switch = section.locator('[role="switch"], button[aria-checked], input[type="checkbox"]').first
        try:
            if await switch.count() == 0 or not await switch.is_visible():
                return
            state = await switch.get_attribute("aria-checked")
            if state == "true":
                await switch.click(timeout=3000, force=True)
                await page.wait_for_timeout(800)
        except Exception:
            pass

    async def dismiss(self) -> None:
        page = self.page
        for _ in range(3):
            clicked = False
            for key in ("got_it", "later", "close"):
                button = page.get_by_role("button", name=labels.exact(key)).first
                try:
                    if await button.count() and await button.is_visible():
                        await button.click(timeout=1200)
                        clicked = True
                        await page.wait_for_timeout(400)
                except Exception:
                    pass
            if not clicked:
                return

    async def click_publish(self) -> None:
        for _ in range(6):
            await self.dismiss()
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self.page.wait_for_timeout(600)
            if await self.press(labels.terms("publish")):
                return
            await self.page.wait_for_timeout(2000)
        raise PageChanged("TikTok upload page changed")

    async def press(self, terms: list[str], scoped: bool = False) -> bool:
        return bool(await self.page.evaluate(PRESS_JS, {"labels": terms, "scoped": scoped}))

    def on_response(self, response) -> None:
        try:
            method = response.request.method.upper()
            url = response.url.lower()
        except Exception:
            return
        if method not in ("POST", "PUT", "PATCH") or "upload" in url:
            return
        if not any(part in url for part in ("/project/post", "/web/project", "/post/", "/publish", "/aweme/v")):
            return
        if 200 <= response.status < 300:
            self.api_ok = True
        elif response.status >= 400:
            self.api_fail = f"{response.status} {url[:120]}"

    async def confirm(self) -> bool:
        page = self.page
        started = page.url
        retries = 0
        for attempt in range(45):
            await self.dismiss()
            text = await self.body_text()
            if self.api_fail or labels.matches(text, "failed"):
                return False
            if self.api_ok or labels.matches(text, "published"):
                return True
            await self.press(labels.terms("confirm"), scoped=True)
            if retries < 2 and attempt and attempt % 5 == 0 and "/upload" in page.url:
                if await self.press(labels.terms("publish")):
                    retries += 1
            if page.url != started and "/upload" not in page.url:
                return True
            await page.wait_for_timeout(2000)
        return False

    async def find_post(self) -> dict:
        page = self.page
        try:
            if "/content" not in page.url:
                await page.goto(CONTENT_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)
            href = await page.evaluate(
                "() => { const a = [...document.querySelectorAll('a[href*=\"/video/\"], a[href*=\"/photo/\"]')][0]; return a ? a.href : ''; }")
        except Exception:
            href = ""
        found = re.search(r"/(video|photo)/(\d+)", href or "")
        return {"ok": True, "id": found.group(2) if found else "", "kind": found.group(1) if found else "",
                "url": href.split("?")[0] if found else "", "sound": getattr(self, "sound", "")}
