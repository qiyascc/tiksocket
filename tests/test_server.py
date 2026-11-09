from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tiksocket.errors import RequestPending
from tiksocket.models import Chat, Message, PostResult, Profile, QRCode, SendResult, VerifyPrompt
from tiksocket.server.app import Account, Manager, build_app


class FakeAuth:
    exists = True

    def load_profile(self):
        return {"username": "demo"}


class FakeSocket:
    def __init__(self):
        self.auth = FakeAuth()
        self.sent = []
        self.codes = []

    @property
    def profile(self):
        return Profile(username="demo")

    def on(self, *args):
        return None

    async def request_qr(self):
        return QRCode(url="https://www.tiktok.com/q")

    async def submit_code(self, code):
        self.codes.append(code)

    async def press_button(self, index):
        self.codes.append(f"button {index}")

    async def whoami(self, live=False):
        return self.profile

    async def chats(self):
        return [Chat(id="0:1:1:2", name="Jane")]

    async def messages(self, chat_id):
        return [Message(id="m1", chat_id=chat_id, text="hi")]

    async def send_message(self, chat_id, text, client_id=""):
        if text == "blocked":
            raise RequestPending("not accepted")
        self.sent.append((chat_id, text, client_id))
        return SendResult(id="m2")

    async def post_photos(self, photos, caption, **options):
        return PostResult(kind="photo", sound=options.get("sound", ""))

    async def post_video(self, video, caption, **options):
        return PostResult(kind="video")

    async def close(self):
        return None


class FakeManager(Manager):
    def __init__(self, tmp_path):
        super().__init__(tmp_path, host=None)
        self.fake = FakeSocket()

    def get(self, name):
        account = self.accounts.get(name)
        if account is None:
            account = self.accounts[name] = Account(name, self.fake)
        return account

    async def close(self):
        return None


@pytest.fixture
async def client(tmp_path):
    manager = FakeManager(tmp_path)
    app = build_app(manager, token="secret")
    async with TestClient(TestServer(app)) as http:
        http.manager = manager
        yield http


H = {"Authorization": "Bearer secret"}


async def test_health_is_open_and_api_needs_token(client):
    assert (await client.get("/health")).status == 200
    assert (await client.get("/api/accounts")).status == 401
    assert (await client.get("/api/accounts?token=secret")).status == 200
    page = await client.get("/")
    assert "TikSocket" in await page.text()


async def test_login_flow_views(client):
    res = await client.post("/api/accounts/main/login/qr", headers=H)
    assert res.status == 200
    account = client.manager.accounts["main"]
    account.login, account.qr = "qr", QRCode(url="https://www.tiktok.com/q")
    view = await (await client.get("/api/accounts/main/login", headers=H)).json()
    assert view["state"] == "qr" and view["qr"]["image"].startswith("data:image/svg+xml")
    account.login, account.prompt = "verify", VerifyPrompt(title="Verify it's you", inputs=[{"i": 0}])
    view = await (await client.get("/api/accounts/main/login", headers=H)).json()
    assert view["prompt"]["needs_code"]


async def test_bad_account_name(client):
    client.manager.get = Manager.get.__get__(client.manager)
    res = await client.get("/api/accounts/bad name!/me", headers=H)
    assert res.status in (400, 404)


async def test_chats_messages_send_and_errors(client):
    chats = await (await client.get("/api/accounts/main/chats", headers=H)).json()
    assert chats["chats"][0]["name"] == "Jane"
    msgs = await (await client.get("/api/accounts/main/chats/0:1:1:2/messages", headers=H)).json()
    assert msgs["messages"][0]["text"] == "hi"
    res = await client.post("/api/accounts/main/chats/0:1:1:2/messages", json={"text": "yo", "client_id": "k"}, headers=H)
    assert (await res.json())["id"] == "m2"
    assert client.manager.fake.sent == [("0:1:1:2", "yo", "k")]
    res = await client.post("/api/accounts/main/chats/0:1:1:2/messages", json={"text": "blocked"}, headers=H)
    assert res.status == 409 and (await res.json())["error"] == "request_pending"


async def test_post_photos_multipart(client):
    from aiohttp import FormData

    form = FormData()
    form.add_field("kind", "photos")
    form.add_field("sound", "lofi")
    form.add_field("file", b"jpg", filename="a.jpg")
    res = await client.post("/api/accounts/main/posts", data=form, headers=H)
    assert (await res.json()) == {"ok": True, "id": "", "kind": "photo", "url": "", "sound": "lofi"}


async def test_code_submission(client):
    res = await client.post("/api/accounts/main/login/code", json={"code": "123456"}, headers=H)
    assert res.status == 200
    assert client.manager.fake.codes == ["123456"]
