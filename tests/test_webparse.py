from __future__ import annotations

import json

import pytest

from tiksocket import webparse as wp
from tiksocket.errors import ActionFailed, LoggedOut, NotFound, PrivateAccount, RateLimited
from tiksocket.web import WebSession


def test_username_and_post_refs():
    assert wp.username("@Some.User_1") == "some.user_1"
    assert wp.username("https://www.tiktok.com/@jane.doe?lang=en") == "jane.doe"
    assert wp.username("not a user!") == ""
    assert wp.post_ref("https://www.tiktok.com/@jane/video/7600000000000000001?x=1") == ("jane", "video", "7600000000000000001")
    assert wp.post_ref("https://www.tiktok.com/@jane/photo/7600000000000000002") == ("jane", "photo", "7600000000000000002")
    assert wp.post_ref("7600000000000000003") == ("", "video", "7600000000000000003")
    assert wp.post_ref("hello") == ("", "", "")
    assert wp.post_url("", "video", "1") == "https://www.tiktok.com/@_/video/1"


def test_universal_script():
    html = '<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">' + json.dumps(
        {"__DEFAULT_SCOPE__": {"webapp.user-detail": {"x": 1}}}) + "</script></html>"
    assert wp.universal(html) == {"webapp.user-detail": {"x": 1}}
    assert wp.universal("<html></html>") == {}


def test_user_from_detail():
    data = {"userInfo": {"user": {"id": "1", "uniqueId": "jane", "nickname": "Jane", "signature": "hi", "verified": True,
                                  "privateAccount": False, "secUid": "SEC", "relation": 1, "bioLink": {"link": "x.com"}},
                         "statsV2": {"followerCount": "1200", "followingCount": "3", "heartCount": "99", "videoCount": "7",
                                     "friendCount": "2"}}}
    user = wp.user_from_detail(data)
    assert (user.username, user.sec_uid, user.followers, user.videos, user.link) == ("jane", "SEC", 1200, 7, "x.com")
    assert user.is_following and not user.is_friend
    assert user.to_dict()["is_following"] is True
    assert wp.user_from_detail({}) is None


def test_user_lists_and_search():
    data = {"userList": [{"user": {"id": "2", "uniqueId": "bob", "nickname": "Bob"}, "stats": {"followerCount": 5}}],
            "hasMore": True, "minCursor": 1700000000, "total": 30}
    rows, page = wp.users_from_list(data)
    assert rows[0].username == "bob" and rows[0].followers == 5
    assert page == {"has_more": True, "min_cursor": "1700000000", "max_cursor": "0", "total": 30}
    found = {"user_list": [{"user_info": {"uid": "3", "unique_id": "amy", "nickname": "Amy", "follower_count": 9,
                                          "avatar_thumb": {"url_list": ["https://a/b.jpg"]}, "follow_status": 0}}],
             "has_more": 1, "cursor": 10}
    rows, page = wp.users_from_search(found)
    assert (rows[0].username, rows[0].avatar, page["cursor"], page["has_more"]) == ("amy", "https://a/b.jpg", "10", True)


def test_posts():
    raw = {"id": "77", "desc": "Flat #baku", "createTime": "1700000000", "author": {"uniqueId": "jane", "id": "1"},
           "statsV2": {"playCount": "1000", "diggCount": "10", "commentCount": "2", "shareCount": "1",
                       "collectCount": "4", "repostCount": "0"},
           "video": {"cover": "c.jpg", "playAddr": "p.mp4", "downloadAddr": "d.mp4", "duration": 15},
           "music": {"title": "Song"}, "digged": True, "collected": False, "privateItem": False,
           "itemCommentStatus": 0, "challenges": [{"title": "baku"}]}
    post = wp.post_from_web(raw)
    assert (post.kind, post.url, post.plays, post.liked, post.download_url, post.hashtags) == (
        "video", "https://www.tiktok.com/@jane/video/77", 1000, True, "d.mp4", ["baku"])
    photo = wp.post_from_web({**raw, "imagePost": {"images": [{"imageURL": {"urlList": ["i1.jpg"]}}]}})
    assert photo.kind == "photo" and photo.images == ["i1.jpg"] and photo.url.endswith("/photo/77")
    assert wp.post_from_detail({"itemInfo": {"itemStruct": raw}}).id == "77"
    assert wp.post_from_detail({}) is None
    rows, page = wp.posts_from_list({"itemList": [raw], "hasMore": True, "cursor": "5"})
    assert len(rows) == 1 and page == {"has_more": True, "cursor": "5"}
    rows, _ = wp.posts_from_search({"data": [{"type": 1, "item": raw}, {"type": 4, "user_list": []}]})
    assert [r.id for r in rows] == ["77"]


def test_manage_list():
    data = {"item_list": [{"item_id": "88", "desc": "Villa", "item_type": 1, "like_count": "5", "play_count": "100",
                           "comment_count": "2", "share_count": "1", "favorite_count": "3", "visibility": 3,
                           "is_pinned": True, "play_addr": ["v.mp4"], "cover_url": ["c.webp"], "duration": 24667,
                           "post_time": "1775333497"}], "has_more": False, "cursor": 50}
    rows, page = wp.posts_from_manage(data, "me")
    post = rows[0]
    assert (post.url, post.private, post.pinned, post.duration, post.play_url) == (
        "https://www.tiktok.com/@me/video/88", True, True, 24, "v.mp4")
    assert page["has_more"] is False


def test_hashtag_comments_notices():
    tag = wp.hashtag_from_detail({"challengeInfo": {"challenge": {"id": "9", "title": "baku"},
                                                    "statsV2": {"videoCount": "4", "viewCount": "100"}}})
    assert (tag.name, tag.views) == ("baku", 100)
    assert wp.hashtag_from_detail({}) is None
    data = {"comments": [{"cid": "c1", "text": "Nice", "user": {"unique_id": "amy", "nickname": "Amy"}, "digg_count": 3,
                          "reply_comment_total": 1, "create_time": 1700000000, "user_digged": 1, "reply_id": "0"}],
            "has_more": 1, "cursor": 20}
    rows, page = wp.comments_from_list(data, "77")
    assert (rows[0].id, rows[0].post_id, rows[0].liked, rows[0].reply_to, page["cursor"]) == ("c1", "77", True, "", "20")
    assert wp.comment_from_publish({"comment": {"cid": "c9", "text": "hey"}}).id == "c9"
    assert wp.comment_from_publish({}) is None
    notices = {"notice_lists": [{"has_more": 1, "cursor": "5", "notice_list": [
        {"nid_str": "n1", "type": 41, "create_time": 1, "has_read": False,
         "digg": {"from_user": [{"unique_id": "amy"}], "aweme": {"aweme_id": "77"}}},
        {"nid_str": "n2", "type": 33, "create_time": 2, "has_read": True, "follow": {"from_user": {"unique_id": "bob"}}},
        {"nid_str": "n3", "type": 999, "create_time": 3, "comment": {"comment": {"text": "Great"}, "from_user": []}}]}]}
    rows, page = wp.notices_from(notices)
    assert [(r.kind, r.users, r.post_id) for r in rows[:2]] == [("like", ["amy"], "77"), ("follow", ["bob"], "")]
    assert rows[2].kind == "comment" and rows[2].text == "Great"
    assert page == {"has_more": True, "cursor": "5"}


@pytest.mark.parametrize("data, error", [
    ({"status_code": 8, "status_msg": "login expired"}, LoggedOut),
    ({"statusCode": 10101}, RateLimited),
    ({"status_code": 10202}, NotFound),
    ({"status_code": 10216}, PrivateAccount),
    ({"status_code": 4, "status_msg": "nope"}, ActionFailed),
])
def test_status_errors(data, error):
    with pytest.raises(error):
        WebSession(None, None).raise_for(data)


def test_status_ok():
    WebSession(None, None).raise_for({"status_code": 0})
    WebSession(None, None).raise_for({"itemList": []})
    assert wp.error_code(0) == ""


class _Resp:
    def __init__(self, status):
        self.status = status


class _Page:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.url = "https://www.tiktok.com/@x"

    async def goto(self, url, **kwargs):
        return _Resp(self.statuses.pop(0))

    async def wait_for_timeout(self, ms):
        return None

    def is_closed(self):
        return False

    async def screenshot(self, **kwargs):
        return None

    def locator(self, selector):
        return _Locator()


class _Locator:
    first = property(lambda self: self)

    async def count(self):
        return 0

    def filter(self, **kwargs):
        return self


class _Auth:
    def debug_folder(self):
        return None


async def test_refused_pages_raise_rate_limited(monkeypatch):
    import tiksocket.web as web_module

    async def no_sleep(_):
        return None

    monkeypatch.setattr(web_module.asyncio, "sleep", no_sleep)
    session = WebSession(None, _Auth())
    with pytest.raises(RateLimited):
        await session._load(_Page([403, 403, 429]), "https://www.tiktok.com/@x/video/1", 0)
    with pytest.raises(NotFound):
        await session._load(_Page([404]), "https://www.tiktok.com/@x/video/1", 0)
    page = _Page([403, 200])
    session.tab = page
    assert await session._load(page, "https://www.tiktok.com/@x", 0) is page


def test_follow_state_from_button():
    from tiksocket.webparse import follow_state

    assert follow_state("Follow") == "none"
    assert follow_state("Follow back") == "none"
    assert follow_state("Following") == "following"
    assert follow_state("Friends") == "friends"
    assert follow_state("Requested") == "requested"
    assert follow_state("") == ""
