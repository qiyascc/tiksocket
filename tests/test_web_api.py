from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tiksocket.cli import build_parser, run_web_command
from tiksocket.errors import NotSupported
from tiksocket.models import ActionResult, Chat, Comment, Hashtag, Notice, Page, Post, SendResult, User
from tiksocket.server.app import Account, Manager, build_app


class Auth:
    exists = True

    def load_profile(self):
        return {"username": "me"}


class WebFake:
    def __init__(self):
        self.auth = Auth()
        self.calls = []

    def on(self, *args):
        return None

    async def close(self):
        return None

    def __getattr__(self, name):
        async def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return RESULTS[name](*args, **kwargs) if callable(RESULTS.get(name)) else RESULTS.get(name)
        return method


def _action(name):
    return lambda *a, **k: ActionResult(action=name, target=str(a[0]) if a else "")


RESULTS = {
    "get_user": lambda name: User(username=name.lstrip("@"), followers=10, relation=1),
    "search_users": lambda q, cursor="0": Page(items=[User(username="amy")], cursor="10", has_more=True),
    "followers": lambda u, c="0", n=30: Page(items=[User(username="bob")], cursor="5"),
    "following": lambda u, c="0", n=30: Page(items=[User(username="sam")]),
    "relationship": lambda u: {"username": u, "following": True, "friends": False, "relation": 1, "private": False},
    "user_posts": lambda u, n=30: [Post(id="1", author=u)],
    "follow": _action("follow"), "unfollow": _action("unfollow"), "block": _action("block"),
    "unblock": _action("unblock"), "remove_follower": _action("remove_follower"),
    "like": _action("like"), "unlike": _action("unlike"), "favorite": _action("favorite"),
    "unfavorite": _action("unfavorite"), "repost": _action("repost"), "undo_repost": _action("undo_repost"),
    "delete_post": _action("delete_post"), "pin_post": _action("pin"), "unpin_post": _action("unpin"),
    "like_comment": lambda p, c: ActionResult(action="like_comment", target=c),
    "delete_comment": lambda p, c: ActionResult(action="delete_comment", target=c),
    "post_settings": lambda p, who="", comments=None: ActionResult(action="post_settings",
                                                                   detail={"who": who, "comments": comments}),
    "share_to_chat": lambda p, u: ActionResult(action="share_to_chat", detail={"to": u}),
    "get_post": lambda p: Post(id="77", author="jane", url=p),
    "comments": lambda p, n=50: [Comment(id="c1", text="hi")],
    "comment": lambda p, t: Comment(id="c2", text=t),
    "reply_comment": lambda p, c, t: Comment(id="c3", text=t, reply_to=c),
    "search_posts": lambda q, c="0": Page(items=[Post(id="9")]),
    "hashtag": lambda n: Hashtag(id="1", name=n.lstrip("#"), views=5),
    "hashtag_posts": lambda n, c=30: [Post(id="8")],
    "feed": lambda kind="foryou", count=10: [Post(id="7")],
    "notifications": lambda count=30, kind="": [Notice(id="n1", kind="like", users=["amy"])],
    "download": lambda p, target=None: b"mp4",
    "update_profile": lambda **k: User(username=k.get("username") or "me", nickname=k.get("nickname") or ""),
    "set_private": lambda v: ActionResult(action="set_private", detail={"private": v}),
    "start_chat": lambda u, t, c="": ("0:1:1:2", SendResult(id="m1")),
    "message_requests": lambda: [Chat(id="0:1:3:4", name="Req")],
    "accept_request": lambda c: None, "delete_request": lambda c: None, "react": lambda c, m, e: None,
    "reply_to": lambda c, m, t, k="": SendResult(id="m9"),
}


class FakeManager(Manager):
    def __init__(self, tmp_path):
        super().__init__(tmp_path, host=None)
        self.fake = WebFake()

    def get(self, name):
        return self.accounts.setdefault(name, Account(name, self.fake))

    async def close(self):
        return None


@pytest.fixture
async def client(tmp_path):
    manager = FakeManager(tmp_path)
    async with TestClient(TestServer(build_app(manager, token="t"))) as http:
        http.manager = manager
        yield http


H = {"Authorization": "Bearer t"}
B = "/api/accounts/main"


async def get(client, path):
    res = await client.get(B + path, headers=H)
    return res.status, await res.json()


async def test_user_routes(client):
    status, data = await get(client, "/users/jane")
    assert status == 200 and data["username"] == "jane" and data["is_following"]
    assert (await get(client, "/users/jane/followers?count=5"))[1]["items"][0]["username"] == "bob"
    assert (await get(client, "/users/jane/following"))[1]["items"][0]["username"] == "sam"
    assert (await get(client, "/users/jane/relation"))[1]["following"] is True
    assert (await get(client, "/users/jane/posts"))[1]["posts"][0]["id"] == "1"
    for verb, action, name in (("POST", "follow", "follow"), ("DELETE", "follow", "unfollow"), ("POST", "block", "block"),
                               ("DELETE", "block", "unblock"), ("DELETE", "follower", "remove_follower")):
        res = await client.request(verb, f"{B}/users/jane/{action}", headers=H)
        assert (await res.json())["action"] == name
    assert (await client.post(f"{B}/users/jane/dance", headers=H)).status == 404


async def test_search_feed_notifications(client):
    assert (await get(client, "/search/users?q=emlak"))[1]["cursor"] == "10"
    assert (await get(client, "/search/posts?q=baku"))[1]["items"][0]["id"] == "9"
    status, data = await get(client, "/hashtags/baku?posts=5")
    assert data["hashtag"]["name"] == "baku" and data["posts"][0]["id"] == "8"
    assert (await get(client, "/feed?kind=explore"))[1]["posts"][0]["id"] == "7"
    assert (await get(client, "/notifications"))[1]["notifications"][0]["users"] == ["amy"]


async def test_post_routes(client):
    url = "https://www.tiktok.com/@jane/video/77"
    status, data = await get(client, f"/post?post={url}")
    assert data["id"] == "77"
    assert (await client.get(f"{B}/post", headers=H)).status == 400
    assert (await get(client, f"/post/comments?post={url}"))[1]["comments"][0]["id"] == "c1"
    for action, name in (("like", "like"), ("unrepost", "undo_repost"), ("delete", "delete_post"), ("pin", "pin")):
        res = await client.post(f"{B}/post/{action}", json={"post": url}, headers=H)
        assert (await res.json())["action"] == name
    res = await client.post(f"{B}/post/comment", json={"post": url, "text": "Nice"}, headers=H)
    assert (await res.json())["text"] == "Nice"
    res = await client.post(f"{B}/post/reply", json={"post": url, "comment_id": "c1", "text": "Yes"}, headers=H)
    assert (await res.json())["reply_to"] == "c1"
    res = await client.post(f"{B}/post/settings", json={"post": url, "who_can_view": "friends", "comments": False},
                            headers=H)
    assert (await res.json())["detail"] == {"who": "friends", "comments": False}
    res = await client.get(f"{B}/post/download?post={url}", headers=H)
    assert await res.read() == b"mp4"


async def test_profile_privacy_and_chats(client):
    res = await client.patch(f"{B}/profile", json={"name": "Jane", "bio": "hi", "avatar": "data:image/png;base64,aGk="},
                             headers=H)
    assert (await res.json())["nickname"] == "Jane"
    kwargs = [c for c in client.manager.fake.calls if c[0] == "update_profile"][0][2]
    assert kwargs["avatar"] == b"hi"
    res = await client.post(f"{B}/privacy", json={"private": True}, headers=H)
    assert (await res.json())["detail"] == {"private": True}
    res = await client.post(f"{B}/chats", json={"username": "jane", "text": "Salam"}, headers=H)
    assert (await res.json())["chat_id"] == "0:1:1:2"
    assert (await get(client, "/requests"))[1]["requests"][0]["name"] == "Req"
    assert (await client.post(f"{B}/requests/0:1:3:4", headers=H)).status == 200
    assert (await client.delete(f"{B}/requests/0:1:3:4", headers=H)).status == 200
    res = await client.post(f"{B}/chats/0:1:1:2/messages/5/react", json={"emoji": "❤️"}, headers=H)
    assert res.status == 200
    res = await client.post(f"{B}/chats/0:1:1:2/messages/5/reply", json={"text": "ok"}, headers=H)
    assert (await res.json())["id"] == "m9"


async def test_not_supported_maps_to_501(client):
    async def nope(*args, **kwargs):
        raise NotSupported("app only")

    client.manager.fake.pin_post = nope
    res = await client.post(f"{B}/post/pin", json={"post": "77"}, headers=H)
    assert res.status == 501 and (await res.json())["error"] == "not_supported"


def parse(*args):
    return build_parser().parse_args(list(args))


def test_cli_parses_new_commands():
    assert parse("follow", "@jane").username == "@jane"
    args = parse("post-settings", "https://x/@a/video/1", "--who", "only_me", "--comments", "off")
    assert (args.who, args.comments) == ("only_me", "off")
    args = parse("profile", "--name", "Jane", "--bio", "Hi", "--avatar", "a.jpg")
    assert (args.name, args.bio, args.avatar, args.username) == ("Jane", "Hi", "a.jpg", None)
    assert parse("feed", "--kind", "explore", "--count", "3").count == 3
    assert parse("reply", "u", "c1", "hey").comment_id == "c1"
    assert parse("react", "0:1:1:2", "5", "❤️").emoji == "❤️"
    assert parse("privacy", "private").mode == "private"
    assert parse("followers").username == ""
    with pytest.raises(SystemExit):
        parse("feed", "--kind", "nope")


@pytest.mark.parametrize("argv, method", [
    (("follow", "jane"), "follow"), (("unrepost", "77"), "undo_repost"), (("pin", "77"), "pin_post"),
    (("user", "jane"), "get_user"), (("comments", "77"), "comments"), (("comment", "77", "hi"), "comment"),
    (("post-settings", "77", "--comments", "on"), "post_settings"), (("notifications",), "notifications"),
    (("new-chat", "jane", "hi"), "start_chat"), (("requests",), "message_requests"),
    (("privacy", "public"), "set_private"), (("hashtag", "baku", "--posts", "2"), "hashtag_posts"),
])
async def test_cli_dispatch(argv, method, capsys):
    fake = WebFake()
    args = parse("--json", *argv)
    assert await run_web_command(args, fake)
    assert method in [c[0] for c in fake.calls]
    assert capsys.readouterr().out.strip()


async def test_cli_settings_flags():
    fake = WebFake()
    await run_web_command(parse("post-settings", "77", "--who", "friends", "--comments", "off"), fake)
    assert [c for c in fake.calls if c[0] == "post_settings"][0][1] == ("77", "friends", False)
    assert not await run_web_command(parse("chats"), fake)
