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
