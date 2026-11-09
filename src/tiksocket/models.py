from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Profile:
    id: str = ""
    username: str = ""
    nickname: str = ""
    avatar: str = ""

    @classmethod
    def from_dict(cls, data: dict | None) -> Profile:
        data = data or {}
        return cls(**{k: str(data.get(k) or "") for k in ("id", "username", "nickname", "avatar")})

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerifyPrompt:
    title: str = ""
    lines: list[str] = field(default_factory=list)
    buttons: list[dict] = field(default_factory=list)
    inputs: list[dict] = field(default_factory=list)
    captcha: bool = False
    screenshot: bytes | None = None

    @property
    def needs_code(self) -> bool:
        return bool(self.inputs)

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("screenshot")
        data["needs_code"] = self.needs_code
        data["has_screenshot"] = self.screenshot is not None
        return data


@dataclass
class QRCode:
    url: str = ""
    image: bytes | None = None
    expires_in: int = 0

    def to_dict(self) -> dict:
        return {"url": self.url, "has_image": self.image is not None, "expires_in": self.expires_in}


@dataclass
class Chat:
    id: str
    name: str = ""
    preview: str = ""
    date: str = ""
    unread: bool = False
    avatar: str = ""
    peer_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Message:
    id: str
    chat_id: str
    kind: str = "text"
    text: str = ""
    from_me: bool = False
    at: int | None = None
    image: str = ""
    thumb: str = ""
    server_id: str = ""
    reply: bool = False
    failed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PostResult:
    ok: bool = True
    id: str = ""
    kind: str = ""
    url: str = ""
    sound: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SendResult:
    id: str = ""
    pending: bool = False
    repeated: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class User:
    id: str = ""
    sec_uid: str = ""
    username: str = ""
    nickname: str = ""
    bio: str = ""
    avatar: str = ""
    verified: bool = False
    private: bool = False
    link: str = ""
    followers: int = 0
    following: int = 0
    likes: int = 0
    videos: int = 0
    friends: int = 0
    relation: int = 0

    @property
    def is_following(self) -> bool:
        return self.relation in (1, 2)

    @property
    def is_friend(self) -> bool:
        return self.relation == 2

    def to_dict(self) -> dict:
        data = asdict(self)
        data["is_following"] = self.is_following
        data["is_friend"] = self.is_friend
        return data


@dataclass
class Post:
    id: str = ""
    kind: str = "video"
    url: str = ""
    author: str = ""
    author_id: str = ""
    caption: str = ""
    created: int = 0
    plays: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    reposts: int = 0
    liked: bool = False
    saved: bool = False
    private: bool = False
    pinned: bool = False
    comments_off: bool = False
    cover: str = ""
    play_url: str = ""
    download_url: str = ""
    duration: int = 0
    music: str = ""
    images: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Comment:
    id: str = ""
    post_id: str = ""
    text: str = ""
    author: str = ""
    author_nickname: str = ""
    likes: int = 0
    replies: int = 0
    created: int = 0
    liked: bool = False
    reply_to: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Hashtag:
    id: str = ""
    name: str = ""
    description: str = ""
    videos: int = 0
    views: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Notice:
    id: str = ""
    kind: str = ""
    type_id: int = 0
    created: int = 0
    read: bool = False
    users: list[str] = field(default_factory=list)
    post_id: str = ""
    text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Page:
    items: list = field(default_factory=list)
    cursor: str = "0"
    has_more: bool = False
    total: int = 0

    def to_dict(self) -> dict:
        return {"items": [item.to_dict() if hasattr(item, "to_dict") else item for item in self.items],
                "cursor": self.cursor, "has_more": self.has_more, "total": self.total}


@dataclass
class ActionResult:
    ok: bool = True
    action: str = ""
    target: str = ""
    changed: bool = True
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
