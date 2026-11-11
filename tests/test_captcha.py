from __future__ import annotations

import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tiksocket.captcha import CaptchaGate, Challenge
from tiksocket.errors import BadInput, CaptchaRequired, NotFound
from tiksocket.server.captcha import CaptchaPage

PUZZLE = """<html><body style="margin:0">
<div role="dialog" class="TUXModal" id="box" style="position:fixed;left:200px;top:100px;width:400px;height:300px;background:#222;color:#fff">
<p>Drag the slider to fit the puzzle</p>
<div id="knob" style="position:absolute;left:10px;top:240px;width:50px;height:40px;background:#fff"></div>
</div>
<script>
let down = null;
document.addEventListener('mousedown', e => { down = e.clientX; });
document.addEventListener('mouseup', e => { if (down !== null && e.clientX - down > 120) document.getElementById('box').remove(); down = null; });
</script></body></html>"""


@pytest.fixture
async def page():
    playwright = pytest.importorskip("playwright.async_api")
    async with playwright.async_playwright() as pw:
        try:
            browser = await pw.chromium.launch()
        except Exception as exc:
            pytest.skip(f"chromium is not installed: {exc}")
        tab = await browser.new_page(viewport={"width": 800, "height": 500})
        await tab.set_content(PUZZLE)
        yield tab
        await browser.close()


async def test_detects_slider_modal(page):
    found = await CaptchaGate().detect(page)
    assert found and found["kind"] == "slide"
    assert "Drag the slider" in found["title"]


async def test_no_captcha_on_plain_page(page):
    await page.set_content("<p>hello</p>")
    gate = CaptchaGate()
    assert await gate.detect(page) is None
    assert await gate.hold(page) is False


async def test_zero_timeout_fails_at_once(page):
    with pytest.raises(CaptchaRequired):
        await CaptchaGate(timeout=0).hold(page)


async def test_waits_for_a_person_and_continues(page):
    events = []

    async def emit(name, data):
        events.append(name)

    gate = CaptchaGate(emit, timeout=30)
    waiting = asyncio.ensure_future(gate.hold(page))
    for _ in range(50):
        if gate.active:
            break
        await asyncio.sleep(0.1)
    assert isinstance(gate.challenge, Challenge)
    assert gate.challenge.kind == "slide"
    assert (await gate.image())[:2] == b"\xff\xd8"
    assert gate.clip == {"x": 188, "y": 88, "width": 424, "height": 324}
    await gate.drag([[0.11, 0.84, 0], [0.4, 0.84, 40], [0.8, 0.84, 40]])
    assert await asyncio.wait_for(waiting, 15) is True
    assert events == ["captcha.required", "captcha.solved"]
    assert not gate.active


async def test_unsolved_captcha_times_out(page):
    events = []

    async def emit(name, data):
        events.append(name)

    with pytest.raises(CaptchaRequired):
        await CaptchaGate(emit, timeout=2).hold(page)
    assert events == ["captcha.required", "captcha.failed"]


async def test_controls_need_a_waiting_captcha():
    gate = CaptchaGate()
    with pytest.raises(NotFound):
        await gate.tap(0.5, 0.5)


async def test_drag_validates_points(page):
    gate = CaptchaGate(timeout=30)
    waiting = asyncio.ensure_future(gate.hold(page))
    for _ in range(50):
        if gate.active:
            break
        await asyncio.sleep(0.1)
    with pytest.raises(BadInput):
        await gate.drag([[0.1, 0.1]])
    with pytest.raises(BadInput):
        await gate.drag(["x"])
    await gate.drag([[0.29, 0.52], [0.6, 0.52]])
    assert await asyncio.wait_for(waiting, 15) is True


class Sock:
    def __init__(self):
        self.pending_captcha = Challenge(id="c1", title="Drag the slider", kind="slide", since=1, expires=601)
        self.calls = []
        self.handlers = {}

    def on(self, name, handler):
        self.handlers[name] = handler

    async def captcha_image(self, quality=80):
        self.calls.append(("image", quality))
        return b"\xff\xd8jpeg"

    async def captcha_press(self, phase, x, y):
        self.calls.append(("press", phase, x, y))

    async def captcha_tap(self, x, y):
        self.calls.append(("tap", x, y))

    async def captcha_drag(self, path):
        self.calls.append(("drag", path))

    async def captcha_refresh(self):
        return True


async def test_cli_page_serves_solver_and_checks_token():
    sock = Sock()
    lines = []
    solver = CaptchaPage(sock, port=0, open_browser=False, out=lines.append).attach()
    assert set(sock.handlers) == {"captcha.required", "captcha.solved", "captcha.failed"}
    async with TestClient(TestServer(solver._app())) as client:
        page = await client.get("/")
        assert "TikCaptcha.mount" in await page.text()
        assert (await client.get("/api/captcha")).status == 401
        auth = {"Authorization": f"Bearer {solver.token}"}
        state = await (await client.get("/api/captcha", headers=auth)).json()
        assert state["pending"]["kind"] == "slide"
        image = await client.get(f"/api/captcha/image?token={solver.token}")
        assert image.content_type == "image/jpeg"
        await client.get(f"/api/captcha/image?token={solver.token}&q=50")
        await client.post("/api/captcha/tap", json={"x": 0.4, "y": 0.6}, headers=auth)
        await client.post("/api/captcha/drag", json={"path": [[0.1, 0.5, 0], [0.6, 0.5, 30]]}, headers=auth)
        for phase, x in (("down", 0.1), ("move", 0.4), ("up", 0.6)):
            await client.post("/api/captcha/press", json={"phase": phase, "x": x, "y": 0.5}, headers=auth)
        assert (await (await client.post("/api/captcha/refresh", headers=auth)).json())["ok"] is True
    assert sock.calls[:2] == [("image", 80), ("image", 50)]
    assert sock.calls[2] == ("tap", 0.4, 0.6)
    assert sock.calls[3][0] == "drag"
    assert [c[1] for c in sock.calls[4:7]] == ["down", "move", "up"]
    assert solver.url.startswith("http://127.0.0.1:0/?token=")


async def test_one_browser_profile_per_account(tmp_path):
    pytest.importorskip("playwright.async_api")
    from tiksocket.browser import BrowserHost

    host = BrowserHost()
    state = {"cookies": [{"name": "sessionid", "value": "x", "domain": ".tiktok.com", "path": "/"}], "origins": []}
    try:
        try:
            first = await host.context(state, tmp_path / "a" / "browser")
        except Exception as exc:
            pytest.skip(f"chromium is not installed: {exc}")
        page = await first.new_page()
        again = await host.context(state, tmp_path / "a" / "browser")
        other = await host.context(state, tmp_path / "b" / "browser")
        assert again is first and other is not first
        assert any(c["name"] == "sessionid" for c in await first.cookies("https://www.tiktok.com"))
        await host.release(first, page)
        assert page.is_closed()
        assert await host.context(state, tmp_path / "a" / "browser") is first
        loose = await host.context(state)
        assert not host.shared(loose)
        await host.release(loose)
        await host.drop(tmp_path / "a" / "browser")
        assert await host.context(state, tmp_path / "a" / "browser") is not first
        assert (tmp_path / "a" / "browser").is_dir()
    finally:
        await host.close()


def test_stale_profile_lock_is_removed(tmp_path):
    import os
    import socket

    from tiksocket.browser import _unlock

    os.symlink(f"{socket.gethostname()}-999999999", tmp_path / "SingletonLock")
    os.symlink("123", tmp_path / "SingletonCookie")
    _unlock(tmp_path)
    assert not os.path.lexists(tmp_path / "SingletonLock")
    os.symlink(f"{socket.gethostname()}-{os.getpid()}", tmp_path / "SingletonLock")
    _unlock(tmp_path)
    assert os.path.lexists(tmp_path / "SingletonLock")
