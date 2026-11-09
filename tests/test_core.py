from __future__ import annotations

import base64
import os
import stat

import pytest

from tiksocket import labels
from tiksocket.auth import use_multi_file_auth_state
from tiksocket.errors import ERRORS, RequestPending, TikSocketError, from_code
from tiksocket.events import EventEmitter
from tiksocket.login import has_session, parse_cookies, qr_from_payload, qr_status
from tiksocket.models import Profile, VerifyPrompt
from tiksocket.terminal import qr_svg, qr_text


def test_labels_match_known_words():
    assert labels.matches("Your video has been posted", "published")
    assert labels.exact("photos").match(" Photos ")
    assert not labels.exact("photos").match("Photos uploaded")
    assert labels.pattern("add_sound").search("+ Add sound")


def test_errors_have_codes_and_status():
    assert from_code("request_pending").__class__ is RequestPending
    assert from_code("weird", "x").code == "weird"
    for code, cls in ERRORS.items():
        error = cls("message")
        assert isinstance(error, TikSocketError)
        assert error.to_dict() == {"error": code, "message": "message"}
        assert 400 <= error.status < 600


async def test_event_emitter_sync_async_wildcard_and_once():
    bus = EventEmitter()
    seen = []
    bus.on("qr", seen.append)

    @bus.on("qr")
    async def later(value):
        seen.append(f"async {value}")

    bus.on("*", lambda event, value: seen.append((event, value)))
    bus.once("qr", lambda value: seen.append("once"))
    await bus.emit("qr", 1)
    await bus.emit("qr", 2)
    assert seen == [1, "async 1", "once", ("qr", 1), 2, "async 2", ("qr", 2)]


async def test_event_emitter_wait_for_and_failing_handler():
    bus = EventEmitter()
    bus.on("boom", lambda value: 1 / 0)
    import asyncio

    waiter = asyncio.ensure_future(bus.wait_for("boom", timeout=2))
    await asyncio.sleep(0)
    await bus.emit("boom", "ok")
    assert await waiter == "ok"


def test_auth_state_encrypts_and_restores(tmp_path, monkeypatch):
    monkeypatch.delenv("TIKSOCKET_KEY", raising=False)
    auth = use_multi_file_auth_state(tmp_path / "acc")
    assert not auth.exists and auth.load_state() is None
    auth.save_state({"cookies": [{"name": "sessionid", "value": "secret"}]})
    auth.save_profile({"username": "demo"})
    raw = (tmp_path / "acc" / "state.bin").read_bytes()
    assert b"secret" not in raw
    key = tmp_path / "acc" / ".key"
    assert stat.S_IMODE(os.stat(key).st_mode) == 0o600
    again = use_multi_file_auth_state(tmp_path / "acc")
    assert again.load_state()["cookies"][0]["value"] == "secret"
    assert again.load_profile()["username"] == "demo"
    again.clear()
    assert not again.exists


def test_auth_state_wrong_key_returns_none(tmp_path):
    auth = use_multi_file_auth_state(tmp_path, key=None)
    auth.save_state({"a": 1})
    from tiksocket.auth import generate_key

    other = use_multi_file_auth_state(tmp_path, key=generate_key())
    assert other.load_state() is None


@pytest.mark.parametrize("raw", [
    "sessionid=abc; tt_csrf_token=x",
    "Cookie: sessionid=abc; other=1",
    '[{"name": "sessionid", "value": "abc"}]',
    {"sessionid": "abc"},
])
def test_parse_cookies_formats(raw):
    cookies = parse_cookies(raw)
    assert has_session(cookies)
    assert all(c["domain"] == ".tiktok.com" for c in cookies)


def test_parse_cookies_rejects_garbage():
    assert parse_cookies("nonsense") == []
    assert not has_session(parse_cookies("a=b"))


def test_qr_payloads():
    image = base64.b64encode(b"png").decode()
    qr = qr_from_payload({"data": {"qrcode_index_url": "https://www.tiktok.com/x", "qrcode": image}})
    assert qr.url == "https://www.tiktok.com/x" and qr.image == b"png"
    assert qr_from_payload({"data": {}}) is None
    assert qr_from_payload("bad") is None
    assert qr_status({"data": {"status": "scanned"}}) == "scanned"
    assert qr_status({"data": {"status": "odd"}}) == ""


def test_terminal_qr_renders():
    text = qr_text("https://www.tiktok.com/login")
    assert text.count("\n") > 10
    assert qr_svg("https://www.tiktok.com/login").startswith(b"<?xml")


def test_models_serialize():
    assert Profile.from_dict({"username": "u", "id": 5}).to_dict() == {"id": "5", "username": "u", "nickname": "",
                                                                        "avatar": ""}
    prompt = VerifyPrompt(title="t", inputs=[{"i": 0}], screenshot=b"x")
    data = prompt.to_dict()
    assert data["needs_code"] and data["has_screenshot"] and "screenshot" not in data
