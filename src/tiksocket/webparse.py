from __future__ import annotations

import json
import re

from .models import Comment, Hashtag, Notice, Post, User

USERNAME = re.compile(r"^@?([A-Za-z0-9_.]{1,30})$")
POST_URL = re.compile(r"tiktok\.com/@([A-Za-z0-9_.]+)/(video|photo)/(\d+)")
POST_ID = re.compile(r"^\d{15,22}$")
UNIVERSAL = re.compile(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', re.S)
NOTICE_TYPES = {33: "follow", 41: "like", 31: "comment", 45: "comment", 22: "mention", 3: "mention", 12: "mention",
                13: "mention"}
LOGGED_OUT_CODES = {8, 2483}
RATE_CODES = {10000, 10101, 10102, 3002060}
NOT_FOUND_CODES = {10201, 10202, 10203, 10204, 10216, 10221, 10222}
PRIVATE_CODES = {10216}


def username(raw: str) -> str:
    text = (raw or "").strip()
    if "tiktok.com/@" in text:
        text = text.split("tiktok.com/@", 1)[1].split("/", 1)[0].split("?", 1)[0]
    found = USERNAME.match(text)
    return found.group(1).lower() if found else ""


def post_ref(raw: str) -> tuple[str, str, str]:
    text = (raw or "").strip()
    found = POST_URL.search(text)
    if found:
        return found.group(1), found.group(2), found.group(3)
    if POST_ID.match(text):
        return "", "video", text
    return "", "", ""


def post_url(user: str, kind: str, post_id: str) -> str:
    return f"https://www.tiktok.com/@{user or '_'}/{kind or 'video'}/{post_id}"


def num(value) -> int:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def first_url(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        urls = value.get("url_list") or value.get("urlList") or []
        return str(urls[0]) if urls else ""
    return ""


def universal(html: str) -> dict:
    found = UNIVERSAL.search(html or "")
    if not found:
        return {}
    try:
        return json.loads(found.group(1)).get("__DEFAULT_SCOPE__") or {}
    except ValueError:
        return {}


def status_of(data) -> tuple[int, str]:
    if not isinstance(data, dict):
        return -1, "no data"
    for key in ("status_code", "statusCode"):
        if key in data:
            return num(data.get(key)), str(data.get("status_msg") or data.get("statusMsg") or "")
    return 0, ""


def error_code(status: int, message: str = "") -> str:
    lower = (message or "").lower()
    if status == 0:
        return ""
    if status in LOGGED_OUT_CODES or "login" in lower:
        return "logged_out"
    if status in PRIVATE_CODES or "private" in lower:
        return "private"
    if status in RATE_CODES or "too fast" in lower or "frequent" in lower:
        return "rate_limited"
    if status in NOT_FOUND_CODES or "not exist" in lower or "not found" in lower:
        return "not_found"
    return "action_failed"


def user_from_detail(data: dict) -> User | None:
    info = (data or {}).get("userInfo") or {}
    raw = info.get("user") or {}
    if not raw.get("id") and not raw.get("uniqueId"):
        return None
    stats = info.get("statsV2") or info.get("stats") or {}
    link = raw.get("bioLink") or {}
    return User(id=str(raw.get("id") or ""), sec_uid=str(raw.get("secUid") or ""), username=str(raw.get("uniqueId") or ""),
                nickname=str(raw.get("nickname") or ""), bio=str(raw.get("signature") or ""),
                avatar=str(raw.get("avatarLarger") or raw.get("avatarMedium") or raw.get("avatarThumb") or ""),
                verified=bool(raw.get("verified")), private=bool(raw.get("privateAccount")),
                link=str(link.get("link") or "") if isinstance(link, dict) else "",
                followers=num(stats.get("followerCount")), following=num(stats.get("followingCount")),
                likes=num(stats.get("heartCount") or stats.get("heart")), videos=num(stats.get("videoCount")),
                friends=num(stats.get("friendCount")), relation=num(raw.get("relation")))


def user_from_web(raw: dict, stats: dict | None = None) -> User:
    stats = stats or {}
    return User(id=str(raw.get("id") or ""), sec_uid=str(raw.get("secUid") or ""), username=str(raw.get("uniqueId") or ""),
                nickname=str(raw.get("nickname") or ""), bio=str(raw.get("signature") or ""),
                avatar=str(raw.get("avatarLarger") or raw.get("avatarMedium") or raw.get("avatarThumb") or ""),
                verified=bool(raw.get("verified")), private=bool(raw.get("privateAccount")),
                followers=num(stats.get("followerCount")), following=num(stats.get("followingCount")),
                likes=num(stats.get("heartCount") or stats.get("heart")), videos=num(stats.get("videoCount")),
                relation=num(raw.get("relation")))


def user_from_app(raw: dict) -> User:
    return User(id=str(raw.get("uid") or ""), sec_uid=str(raw.get("sec_uid") or ""), username=str(raw.get("unique_id") or ""),
                nickname=str(raw.get("nickname") or ""), bio=str(raw.get("signature") or ""),
                avatar=first_url(raw.get("avatar_thumb") or raw.get("avatar_168x168")),
                verified=bool(raw.get("custom_verify") or raw.get("enterprise_verify_reason")),
                followers=num(raw.get("follower_count")), likes=num(raw.get("total_favorited")),
                relation=num(raw.get("follow_status")))


def users_from_list(data: dict) -> tuple[list[User], dict]:
    rows = [user_from_web(row.get("user") or {}, row.get("statsV2") or row.get("stats") or {})
            for row in (data or {}).get("userList") or []]
    page = {"has_more": bool((data or {}).get("hasMore")), "min_cursor": str((data or {}).get("minCursor") or 0),
            "max_cursor": str((data or {}).get("maxCursor") or 0), "total": num((data or {}).get("total"))}
    return [row for row in rows if row.username], page


def users_from_search(data: dict) -> tuple[list[User], dict]:
    rows = [user_from_app(row.get("user_info") or {}) for row in (data or {}).get("user_list") or []]
    return [row for row in rows if row.username], {"has_more": bool((data or {}).get("has_more")),
                                                   "cursor": str((data or {}).get("cursor") or 0)}


def post_from_web(raw: dict) -> Post:
    author = raw.get("author") or {}
    if isinstance(author, str):
        author = {"uniqueId": author}
    stats = raw.get("statsV2") or raw.get("stats") or {}
    video = raw.get("video") or {}
    images = ((raw.get("imagePost") or {}).get("images") or [])
    music = raw.get("music") or {}
    kind = "photo" if images else "video"
    user = str(author.get("uniqueId") or "")
    pid = str(raw.get("id") or "")
    return Post(id=pid, kind=kind, url=post_url(user, kind, pid) if pid else "", author=user,
                author_id=str(author.get("id") or ""), caption=str(raw.get("desc") or ""),
                created=num(raw.get("createTime")), plays=num(stats.get("playCount")), likes=num(stats.get("diggCount")),
                comments=num(stats.get("commentCount")), shares=num(stats.get("shareCount")),
                saves=num(stats.get("collectCount")), reposts=num(stats.get("repostCount")),
                liked=bool(raw.get("digged")), saved=bool(raw.get("collected")), private=bool(raw.get("privateItem")),
                pinned=bool(raw.get("isPinnedItem")), comments_off=num(raw.get("itemCommentStatus")) != 0,
                cover=str(video.get("cover") or video.get("originCover") or ""),
                play_url=str(video.get("playAddr") or ""), download_url=str(video.get("downloadAddr") or ""),
                duration=num(video.get("duration")), music=str(music.get("title") or ""),
                images=[first_url(i.get("imageURL") or {}) for i in images if isinstance(i, dict)],
                hashtags=[str(c.get("title") or "") for c in raw.get("challenges") or [] if isinstance(c, dict)])


def post_from_app(raw: dict) -> Post:
    author = raw.get("author") or {}
    stats = raw.get("statistics") or {}
    video = raw.get("video") or {}
    images = ((raw.get("image_post_info") or {}).get("images") or [])
    kind = "photo" if images else "video"
    user = str(author.get("unique_id") or "")
    pid = str(raw.get("aweme_id") or "")
    return Post(id=pid, kind=kind, url=post_url(user, kind, pid) if pid else "", author=user,
                author_id=str(author.get("uid") or ""), caption=str(raw.get("desc") or ""),
                created=num(raw.get("create_time")), plays=num(stats.get("play_count")), likes=num(stats.get("digg_count")),
                comments=num(stats.get("comment_count")), shares=num(stats.get("share_count")),
                saves=num(stats.get("collect_count")), cover=first_url(video.get("cover")),
                play_url=first_url(video.get("play_addr")), download_url=first_url(video.get("download_addr")),
                duration=num(video.get("duration")) // (1000 if num(video.get("duration")) > 1000 else 1),
                music=str((raw.get("music") or {}).get("title") or ""))


VISIBILITY = {1: "everyone", 2: "friends", 3: "only_me"}


def post_from_manage(raw: dict, owner: str = "") -> Post:
    play = raw.get("play_addr") or []
    cover = raw.get("cover_url") or []
    kind = "photo" if num(raw.get("item_type")) == 2 or raw.get("image_post_info") else "video"
    pid = str(raw.get("item_id") or "")
    return Post(id=pid, kind=kind, url=post_url(owner, kind, pid) if pid else "", author=owner,
                caption=str(raw.get("desc") or ""), created=num(raw.get("post_time") or raw.get("create_time")),
                plays=num(raw.get("play_count")), likes=num(raw.get("like_count")), comments=num(raw.get("comment_count")),
                shares=num(raw.get("share_count")), saves=num(raw.get("favorite_count")),
                private=num(raw.get("visibility")) == 3, pinned=bool(raw.get("is_pinned")),
                cover=str(cover[0]) if isinstance(cover, list) and cover else first_url(cover),
                play_url=str(play[0]) if isinstance(play, list) and play else first_url(play),
                duration=num(raw.get("duration")) // (1000 if num(raw.get("duration")) > 1000 else 1))


def posts_from_manage(data: dict, owner: str = "") -> tuple[list[Post], dict]:
    rows = [post_from_manage(row, owner) for row in (data or {}).get("item_list") or [] if isinstance(row, dict)]
    return rows, {"has_more": bool((data or {}).get("has_more")), "cursor": str((data or {}).get("cursor") or 0)}


def post_from_detail(data: dict) -> Post | None:
    raw = ((data or {}).get("itemInfo") or {}).get("itemStruct") or {}
    return post_from_web(raw) if raw.get("id") else None


def posts_from_list(data: dict) -> tuple[list[Post], dict]:
    rows = [post_from_web(row) for row in (data or {}).get("itemList") or [] if isinstance(row, dict)]
    return rows, {"has_more": bool((data or {}).get("hasMore")), "cursor": str((data or {}).get("cursor") or 0)}


def posts_from_search(data: dict) -> tuple[list[Post], dict]:
    rows = []
    for entry in (data or {}).get("data") or []:
        if isinstance(entry, dict) and entry.get("type") == 1 and isinstance(entry.get("item"), dict):
            rows.append(post_from_web(entry["item"]))
    return rows, {"has_more": bool((data or {}).get("has_more")), "cursor": str((data or {}).get("cursor") or 0)}


def hashtag_from_detail(data: dict) -> Hashtag | None:
    info = (data or {}).get("challengeInfo") or {}
    raw = info.get("challenge") or {}
    if not raw.get("id"):
        return None
    stats = info.get("statsV2") or info.get("stats") or {}
    return Hashtag(id=str(raw["id"]), name=str(raw.get("title") or ""), description=str(raw.get("desc") or ""),
                   videos=num(stats.get("videoCount")), views=num(stats.get("viewCount")))


def comment_from(raw: dict, post_id: str = "") -> Comment:
    user = raw.get("user") or {}
    return Comment(id=str(raw.get("cid") or ""), post_id=str(raw.get("aweme_id") or post_id), text=str(raw.get("text") or ""),
                   author=str(user.get("unique_id") or ""), author_nickname=str(user.get("nickname") or ""),
                   likes=num(raw.get("digg_count")), replies=num(raw.get("reply_comment_total")),
                   created=num(raw.get("create_time")), liked=bool(raw.get("user_digged")),
                   reply_to=str(raw.get("reply_id") or "") if str(raw.get("reply_id") or "0") != "0" else "")


def comments_from_list(data: dict, post_id: str = "") -> tuple[list[Comment], dict]:
    rows = [comment_from(row, post_id) for row in (data or {}).get("comments") or [] if isinstance(row, dict)]
    return [row for row in rows if row.id], {"has_more": bool((data or {}).get("has_more")),
                                             "cursor": str((data or {}).get("cursor") or 0)}


def comment_from_publish(data: dict) -> Comment | None:
    raw = (data or {}).get("comment") or {}
    return comment_from(raw) if raw.get("cid") else None


def notices_from(data: dict) -> tuple[list[Notice], dict]:
    rows, more, cursor = [], False, "0"
    for group in (data or {}).get("notice_lists") or []:
        more = more or bool(group.get("has_more"))
        cursor = str(group.get("cursor") or group.get("min_time") or cursor)
        for raw in group.get("notice_list") or []:
            rows.append(notice_from(raw))
    return rows, {"has_more": more, "cursor": cursor}


def notice_from(raw: dict) -> Notice:
    kind_id = num(raw.get("type"))
    body = next((raw[k] for k in ("digg", "follow", "comment", "at", "text", "announcement", "system")
                 if isinstance(raw.get(k), dict)), {})
    body_key = next((k for k in ("digg", "follow", "comment", "at") if isinstance(raw.get(k), dict)), "")
    kind = NOTICE_TYPES.get(kind_id) or {"digg": "like", "at": "mention"}.get(body_key, body_key or "system")
    users = body.get("from_user") or body.get("user") or []
    if isinstance(users, dict):
        users = [users]
    names = [str(u.get("unique_id") or "") for u in users if isinstance(u, dict)]
    aweme = body.get("aweme") or {}
    comment = body.get("comment") or {}
    text = str(body.get("content") or (comment.get("text") if isinstance(comment, dict) else "") or body.get("title") or "")
    return Notice(id=str(raw.get("nid_str") or raw.get("nid") or ""), kind=kind, type_id=kind_id,
                  created=num(raw.get("create_time")), read=bool(raw.get("has_read")), users=[n for n in names if n],
                  post_id=str(aweme.get("aweme_id") or "") if isinstance(aweme, dict) else "", text=text)


def follow_state(label: str) -> str:
    text = (label or "").strip().lower()
    if not text:
        return ""
    if "friend" in text:
        return "friends"
    if "request" in text:
        return "requested"
    if "following" in text or "unfollow" in text:
        return "following"
    if "follow" in text:
        return "none"
    return ""
