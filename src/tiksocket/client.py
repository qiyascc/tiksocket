from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from .auth import AuthState, use_multi_file_auth_state
from .browser import BrowserHost, BrowserOptions, snapshot
from .constants import CAPTION_MAX, MAX_VIDEO, PHOTO_MAX, TITLE_MAX
from .errors import BadInput, BadMedia, LoggedOut, NotConnected, TikSocketError
from .events import EventEmitter
from .login import QRLogin, cookie_login, fetch_profile
from .messenger import Messenger
from .models import Chat, Message, PostResult, Profile, QRCode, SendResult
from .upload import Uploader

log = logging.getLogger("tiksocket")
SOUND_MODES = ("none", "auto", "search")


class TikSocket(EventEmitter):
    def __init__(self, auth: AuthState | str | os.PathLike = "tiksocket_auth", *, headless: bool = True,
                 proxy: str = "", timezone: str = "UTC", browser: BrowserHost | None = None, uploads: int = 2):
        super().__init__()
        self.auth = auth if isinstance(auth, AuthState) else use_multi_file_auth_state(auth)
        self.host = browser or BrowserHost(BrowserOptions(headless=headless, proxy=proxy, timezone=timezone))
        self.own_host = browser is None
        self.timezone = timezone
        self.messenger = Messenger(self.host, self.auth, self.emit, timezone)
        self.login: QRLogin | None = None
        self.uploads = asyncio.Semaphore(max(1, uploads))
        self.state = "close"

    @property
    def profile(self) -> Profile:
        return Profile.from_dict(self.auth.load_profile())

    @property
    def connected(self) -> bool:
        return self.auth.exists and self.state == "open"

    async def _update(self, connection: str, **extra) -> None:
        self.state = connection
        await self.emit("connection.update", {"connection": connection, **extra})

    async def connect(self, check: bool = True) -> Profile | None:
        if self.auth.exists:
            if not check:
                await self._update("open", profile=self.profile.to_dict())
                return self.profile
            profile = await self.whoami(live=True)
            if profile is not None:
                return profile
        await self._update("connecting")
        await self.request_qr()
        return None

    async def request_qr(self) -> QRCode:
        if self.login is not None:
            await self.login.cancel()
        self.login = QRLogin(self.host, self.auth, self.emit)
        qr = await self.login.start()
        asyncio.create_task(self._finish_login(self.login))
        return qr

    async def _finish_login(self, login: QRLogin) -> None:
        try:
            profile = await login.wait()
        except TikSocketError as exc:
            await self._update("close", reason=exc.code)
            return
        except asyncio.CancelledError:
            return
        if self.login is login:
            self.login = None
        await self._update("open", profile=profile.to_dict(), is_new_login=True)
        await self.emit("creds.update", profile.to_dict())

    async def wait_for_login(self, timeout: float | None = None) -> Profile:
        if self.login is None:
            if self.auth.exists:
                return self.profile
            raise NotConnected("no login in progress")
        return await self.login.wait(timeout)

    def _login(self) -> QRLogin:
        if self.login is None:
            raise NotConnected("no login in progress")
        return self.login

    async def submit_code(self, code: str) -> None:
        await self._login().submit_code(code)

    async def press_button(self, index: int) -> None:
        await self._login().press(index)

    async def tap(self, x: float, y: float) -> None:
        await self._login().tap(x, y)

    async def drag(self, x: float, y: float, x2: float, y2: float) -> None:
        await self._login().drag(x, y, x2, y2)

    async def verify_prompt(self):
        return await self._login().prompt()

    async def login_with_cookies(self, cookies) -> Profile:
        profile = await cookie_login(self.host, self.auth, cookies)
        await self._update("open", profile=profile.to_dict(), is_new_login=True)
        return profile

    async def whoami(self, live: bool = False) -> Profile | None:
        if not self.auth.exists:
            return None
        if not live:
            return self.profile
        context = await self.host.context(self.auth.load_state())
        try:
            profile = await fetch_profile(context)
            if profile is None:
                await self._update("close", reason="logged_out")
                return None
            self.auth.save_state(await context.storage_state())
            self.auth.save_profile(profile.to_dict())
        finally:
            await context.close()
        await self._update("open", profile=profile.to_dict())
        return profile

    async def logout(self) -> None:
        await self.messenger.close()
        self.auth.clear()
        await self._update("close", reason="logged_out")

    async def _post(self, files: list[bytes] | list[str], caption: str, mode: str, title: str = "",
                    sound: str = "", auto_sound: bool = False, dry_run: bool = False) -> PostResult:
        state = self.auth.load_state()
        if state is None:
            raise NotConnected("log in first")
        sound_mode = "search" if sound else ("auto" if auto_sound else "none")
        paths, temp = [], []
        suffix = ".mp4" if mode == "video" else ".jpg"
        for item in files:
            if isinstance(item, (bytes, bytearray)):
                if not item or len(item) > MAX_VIDEO:
                    raise BadMedia("file is empty or too large")
                handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
                handle.write(item)
                handle.close()
                temp.append(handle.name)
                paths.append(handle.name)
            else:
                path = Path(item)
                if not path.is_file():
                    raise BadInput(f"file not found: {path}")
                paths.append(str(path))
        if not paths:
            raise BadMedia("nothing to upload")
        async with self.uploads:
            context = await self.host.context(state)
            page = await context.new_page()
            try:
                result = await Uploader(page).run(paths, (caption or "")[:CAPTION_MAX], mode=mode,
                                                  title=(title or "")[:TITLE_MAX], sound_mode=sound_mode,
                                                  sound=(sound or "")[:80], dry_run=dry_run)
                self.auth.save_state(await context.storage_state())
            except LoggedOut:
                await snapshot(page, self.auth.debug_folder(), "upload-logged-out.png")
                await self._update("close", reason="logged_out")
                raise
            except TikSocketError:
                await snapshot(page, self.auth.debug_folder(), "upload-error.png")
                raise
            finally:
                await context.close()
                for name in temp:
                    try:
                        os.unlink(name)
                    except OSError:
                        pass
        post = PostResult(ok=True, id=result.get("id") or "", kind=result.get("kind") or mode, url=result.get("url") or "",
                          sound=result.get("sound") or "")
        if not dry_run:
            await self.emit("posts.upsert", post)
        return post

    async def post_video(self, video: bytes | str, caption: str = "", *, sound: str = "", auto_sound: bool = False,
                         dry_run: bool = False) -> PostResult:
        return await self._post([video], caption, "video", sound=sound, auto_sound=auto_sound, dry_run=dry_run)

    async def post_photos(self, photos: Iterable[bytes | str], caption: str = "", *, title: str = "", sound: str = "",
                          auto_sound: bool = False, dry_run: bool = False) -> PostResult:
        items = list(photos)
        if not items or len(items) > PHOTO_MAX:
            raise BadInput(f"send between 1 and {PHOTO_MAX} photos")
        return await self._post(items, caption, "photo", title=title, sound=sound, auto_sound=auto_sound, dry_run=dry_run)

    async def chats(self) -> list[Chat]:
        return await self.messenger.chats()

    async def messages(self, chat_id: str) -> list[Message]:
        return await self.messenger.messages(chat_id)

    async def send_message(self, chat_id: str, text: str, client_id: str = "") -> SendResult:
        result = await self.messenger.send(chat_id, text, client_id)
        await self.emit("messages.sent", {"chat_id": chat_id, "text": text, **result.to_dict()})
        return result

    def start_listening(self, interval: float = 25.0, history: bool = False) -> asyncio.Task:
        return self.messenger.start_listening(interval, history)

    async def close(self) -> None:
        if self.login is not None:
            await self.login.cancel()
        await self.messenger.close()
        if self.own_host:
            await self.host.close()

    async def __aenter__(self) -> TikSocket:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()


def make_tiktok_socket(auth: AuthState | str | os.PathLike = "tiksocket_auth", **options) -> TikSocket:
    return TikSocket(auth, **options)
