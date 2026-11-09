from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from playwright.async_api import BrowserContext, Page

from . import parse
from .auth import AuthState
from .browser import BrowserHost, body_text, snapshot
from .constants import INBOX_URLS
from .errors import (
    BadInput,
    LoggedOut,
    NotConnected,
    NotDelivered,
    NotFound,
    RateLimited,
    RequestPending,
    TikSocketError,
    Unavailable,
    from_code,
)
from .js import CHATS_JS, ITEMS_JS, SCROLL_JS
from .models import Chat, Message, SendResult

log = logging.getLogger("tiksocket")
Emit = Callable[[str, object], Awaitable[None]]

ITEM = "[data-e2e=dm-new-conversation-item], [data-conv-id]"
EDITOR = ("[data-e2e=dm-new-input-editor] [contenteditable=true]", "[data-e2e=message-input-area] [contenteditable=true]",
          "[contenteditable=true][role=textbox]", "[aria-label='Send a message...']")
LIST = "[data-e2e=dm-new-message-list], [data-e2e=dm-new-chatbox]"
CLOSERS = ("[role=dialog] [aria-label=Close]", "[role=dialog] button[aria-label*=close i]", ".TUXModal-closeButton",
           "[data-e2e=modal-close-inner-button]", "[role=dialog] svg[role=button]")
TRIES = 3
SENT_TTL = 6 * 3600


class Messenger:
    def __init__(self, host: BrowserHost, auth: AuthState, emit: Emit, timezone: str = "UTC"):
        self.host = host
        self.auth = auth
        self.emit = emit
        self.zone = ZoneInfo(timezone)
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.lock = asyncio.Lock()
        self.inbox_url = INBOX_URLS[0]
        self.listener: asyncio.Task | None = None

    @property
    def me(self) -> str:
        return (self.auth.load_profile().get("username") or "").lower()

    @property
    def me_id(self) -> str:
        return str(self.auth.load_profile().get("id") or "")

    async def _page(self) -> Page:
        if self.page is not None and not self.page.is_closed():
            return self.page
        state = self.auth.load_state()
        if state is None:
            raise NotConnected("log in first")
        self.context = await self.host.context(state)
        self.page = await self.context.new_page()
        await self._open_inbox(fresh=True)
        return self.page

    async def _open_inbox(self, fresh: bool = False) -> None:
        page = self.page
        delay = 2
        for attempt in range(TRIES):
            try:
                if fresh or attempt or "/messages" not in page.url:
                    await page.goto(self.inbox_url, wait_until="domcontentloaded", timeout=60000)
                await self._ready()
                return
            except TikSocketError:
                raise
            except Exception as exc:
                log.warning("inbox load failed (try %s): %s", attempt + 1, type(exc).__name__)
                await asyncio.sleep(delay)
                delay *= 2
        await snapshot(page, self.auth.debug_folder(), "dm-load-error.png")
        raise Unavailable("TikTok messages did not load")

    async def _ready(self) -> None:
        page = self.page
        deadline = time.time() + 30
        while time.time() < deadline:
            if "/login" in page.url:
                raise LoggedOut("TikTok session ended")
            if "business-suite" in page.url and self.inbox_url != INBOX_URLS[1]:
                self.inbox_url = INBOX_URLS[1]
                await page.goto(self.inbox_url, wait_until="domcontentloaded", timeout=60000)
                continue
            await self._dismiss()
            if await page.locator(ITEM).count():
                await self._settle_list()
                return
            text = await body_text(page)
            if "Messages" not in text and parse.blocked(text) == "logged_out":
                raise LoggedOut("TikTok session ended")
            if "no messages" in text.lower():
                return
            await page.wait_for_timeout(1500)
        raise TimeoutError("inbox not ready")

    async def _settle_list(self) -> None:
        page = self.page
        last, steady = -1, 0
        for _ in range(16):
            count = await page.locator(ITEM).count()
            named = await page.locator("[data-e2e=dm-new-conversation-nickname]").count()
            steady = steady + 1 if count == last and named >= count else 0
            if steady >= 2:
                return
            last = count
            await page.wait_for_timeout(500)

    async def _dismiss(self) -> None:
        page = self.page
        dialogs = page.locator("[role=dialog]:visible")
        if not await dialogs.count():
            return
        for selector in CLOSERS:
            button = page.locator(selector).first
            try:
                if await button.count() and await button.is_visible():
                    await button.click(timeout=2000)
                    await page.wait_for_timeout(500)
                    if not await dialogs.count():
                        return
            except Exception:
                continue
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

    async def _reset(self) -> None:
        if self.context is not None:
            try:
                await self.context.close()
            except Exception:
                pass
        self.context, self.page = None, None

    async def chats(self) -> list[Chat]:
        async with self.lock:
            page = await self._page()
            try:
                await self._open_inbox()
                raw = await page.evaluate(CHATS_JS)
            except TikSocketError:
                raise
            except Exception as exc:
                await snapshot(page, self.auth.debug_folder(), "dm-chats-error.png")
                await self._reset()
                raise Unavailable("could not read chats") from exc
        me_id = self.me_id
        return [Chat(id=row["id"], name=row["name"], preview=row["preview"], date=row["date"], unread=row["unread"],
                     avatar=row["avatar"], peer_id=parse.peer_of(row["id"], me_id)) for row in parse.chats(raw)]

    async def _open_chat(self, chat_id: str) -> None:
        page = self.page
        target = page.locator(f'[data-conv-id="{chat_id}"]').first
        for attempt in range(TRIES):
            await self._dismiss()
            if not await target.count():
                await self._scroll_find(chat_id)
            if not await target.count():
                if attempt == TRIES - 1:
                    raise NotFound(f"chat {chat_id} not found")
                await self._open_inbox(fresh=True)
                continue
            try:
                await target.click(timeout=8000)
                await page.locator(LIST).first.wait_for(timeout=15000)
                await page.wait_for_timeout(1200)
                return
            except Exception:
                await page.wait_for_timeout(1500 * (attempt + 1))
        await snapshot(page, self.auth.debug_folder(), "dm-open-error.png")
        raise Unavailable("could not open chat")

    async def _scroll_find(self, chat_id: str) -> None:
        for _ in range(12):
            moved = await self.page.evaluate(SCROLL_JS, chat_id)
            await self.page.wait_for_timeout(700)
            if await self.page.locator(f'[data-conv-id="{chat_id}"]').count() or not moved:
                return

    async def _items(self) -> dict:
        raw = await self.page.evaluate(ITEMS_JS)
        return parse.messages(raw, self.me, datetime.now(self.zone), limit=60)

    async def messages(self, chat_id: str) -> list[Message]:
        if not parse.CONV.match(chat_id or ""):
            raise BadInput("bad chat id")
        async with self.lock:
            await self._page()
            try:
                await self._open_chat(chat_id)
                data = await self._items()
            except TikSocketError:
                raise
            except Exception as exc:
                await snapshot(self.page, self.auth.debug_folder(), "dm-history-error.png")
                await self._reset()
                raise Unavailable("could not read messages") from exc
        return [_message(chat_id, row) for row in parse.delivered(data["items"])]

    async def _editor(self):
        for selector in EDITOR:
            box = self.page.locator(selector).first
            try:
                if await box.count() and await box.is_visible():
                    return box
            except Exception:
                continue
        return None

    async def _type(self, box, text: str) -> None:
        page = self.page
        await box.click(timeout=5000)
        if (await box.inner_text(timeout=2000)).strip():
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
        lines = text.split("\n")
        for index, line in enumerate(lines):
            if line:
                await page.keyboard.insert_text(line)
            if index < len(lines) - 1:
                await page.keyboard.press("Shift+Enter")
        await page.wait_for_timeout(300)
        if not (await box.inner_text(timeout=2000)).strip():
            raise RuntimeError("editor stayed empty")
        await page.keyboard.press("Enter")

    async def _check(self, before: set, text: str) -> tuple[str, str]:
        data = await self._items()
        return parse.outcome(data["items"], before, text, data.get("notice") or "")

    async def _settle(self, before: set, text: str) -> tuple[str, str]:
        deadline = time.time() + 20
        state, value = "none", ""
        while time.time() < deadline:
            await self.page.wait_for_timeout(800)
            state, value = await self._check(before, text)
            if state in ("sent", "failed"):
                break
        return state, value

    async def send(self, chat_id: str, text: str, client_id: str = "") -> SendResult:
        text = (text or "").strip()[:4000]
        if not parse.CONV.match(chat_id or ""):
            raise BadInput("bad chat id")
        if not text:
            raise BadInput("empty message")
        async with self.lock:
            sent = self._sent()
            known = sent.get(client_id) if client_id else None
            if known:
                if known.get("error"):
                    raise from_code(known["error"], "already tried")
                return SendResult(id=known["id"], repeated=True)
            await self._page()
            await self._open_chat(chat_id)
            before = {row["id"] for row in (await self._items())["items"]}
            state, value = "none", ""
            for _ in range(TRIES):
                box = await self._editor()
                if box is None:
                    await self._dismiss()
                    await self._open_chat(chat_id)
                    continue
                try:
                    await self._type(box, text)
                except Exception as exc:
                    log.warning("typing failed: %s", type(exc).__name__)
                    state, value = await self._check(before, text)
                    if state != "none":
                        break
                    continue
                state, value = await self._settle(before, text)
                if state != "none":
                    break
                if parse.blocked(await body_text(self.page)) == "rate_limited":
                    await snapshot(self.page, self.auth.debug_folder(), "dm-rate-limited.png")
                    raise RateLimited("TikTok asks to slow down")
            if state == "failed":
                await snapshot(self.page, self.auth.debug_folder(), "dm-send-refused.png")
                self._remember(client_id, "", value)
                if value == "request_pending":
                    raise RequestPending("the other side has not accepted your message request yet")
                raise NotDelivered("TikTok refused the message")
            if state == "none":
                await snapshot(self.page, self.auth.debug_folder(), "dm-send-error.png")
                raise Unavailable("message did not appear in the chat")
            self._remember(client_id, value, "")
        return SendResult(id=value, pending=state == "pending")

    def _sent(self) -> dict:
        cutoff = time.time() - SENT_TTL
        return {k: v for k, v in self.auth.load_json("sent.json").items() if isinstance(v, dict) and v.get("at", 0) > cutoff}

    def _remember(self, client_id: str, sent_id: str, error: str) -> None:
        if not client_id:
            return
        data = self._sent()
        data[client_id] = {"id": sent_id, "error": error, "at": time.time()}
        self.auth.save_json("sent.json", data)

    async def listen(self, interval: float = 25.0, history: bool = False) -> None:
        seen = self.auth.load_json("seen.json")
        first = not seen
        while True:
            try:
                rows = await self.chats()
                await self.emit("chats.update", rows)
                for chat in rows:
                    state = seen.get(chat.id) or {}
                    sig = f"{chat.preview}|{chat.date}"
                    if state.get("sig") == sig:
                        continue
                    items = await self.messages(chat.id)
                    known = set(state.get("ids") or [])
                    fresh = [m for m in items if m.id not in known]
                    seen[chat.id] = {"sig": sig, "ids": [m.id for m in items][-80:]}
                    if fresh and (history or not first):
                        await self.emit("messages.upsert", {"chat": chat, "messages": fresh,
                                                            "type": "notify" if not first else "append"})
                self.auth.save_json("seen.json", seen)
                first = False
            except LoggedOut as exc:
                await self.emit("connection.update", {"connection": "close", "reason": exc.code})
                return
            except asyncio.CancelledError:
                raise
            except TikSocketError as exc:
                log.warning("listen round failed: %s", exc.code)
            except Exception:
                log.exception("listen round crashed")
            await asyncio.sleep(interval)

    def start_listening(self, interval: float = 25.0, history: bool = False) -> asyncio.Task:
        if self.listener is None or self.listener.done():
            self.listener = asyncio.create_task(self.listen(interval, history))
        return self.listener

    async def close(self) -> None:
        if self.listener is not None:
            self.listener.cancel()
        await self._reset()


def _message(chat_id: str, row: dict) -> Message:
    return Message(id=row["id"], chat_id=chat_id, kind=row.get("kind") or "text", text=row.get("text") or "",
                   from_me=bool(row.get("from_me")), at=row.get("at"), image=row.get("image") or "",
                   thumb=row.get("thumb") or "", server_id=row.get("server") or "", reply=bool(row.get("reply")),
                   failed=bool(row.get("failed")))
