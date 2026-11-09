from __future__ import annotations

import re
from datetime import datetime, timedelta

MONTHS = {name: i for i, name in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
     "december"], start=1)}
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
CLOCK = re.compile(r"(\d{1,2}):(\d{2})")
FULL = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})")
SHORT_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
REPLY_PREFIX = ("replied to you", "you replied to them", "you replied", "replied to themselves")
RATE_WORDS = ("too fast", "too many", "try again later", "slow down", "frequently")
LOGIN_WORDS = ("log in to tiktok", "log in or sign up", "use qr code")
CONV = re.compile(r"^0:1:\d+:\d+$")
SERVER_ID = re.compile(r"msg-(\d+)")
REQUEST_WORDS = ("accepts your message request", "only send up to", "can't send", "cannot send", "not delivered",
                 "couldn't send", "failed to send")


def refused(text: str) -> str:
    lower = (text or "").lower()
    if "accepts your message request" in lower or "only send up to" in lower:
        return "request_pending"
    if any(word in lower for word in REQUEST_WORDS):
        return "not_delivered"
    return blocked(text)


def parse_stamp(raw: str, now: datetime) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    clock = CLOCK.search(text)
    hour, minute = (int(clock.group(1)), int(clock.group(2))) if clock else (12, 0)
    lower = text.lower()
    full = FULL.search(text)
    if full and full.group(1).lower() in MONTHS:
        try:
            found = now.replace(year=int(full.group(3)), month=MONTHS[full.group(1).lower()], day=int(full.group(2)),
                                hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            return None
        return min(found, now)
    short = SHORT_DATE.search(text)
    if short:
        try:
            found = now.replace(year=int(short.group(3)), month=int(short.group(1)), day=int(short.group(2)),
                                hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            return None
        return min(found, now)
    base = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if lower.startswith("yesterday"):
        return base - timedelta(days=1)
    for index, name in enumerate(DAYS):
        if lower.startswith(name):
            back = (now.weekday() - index) % 7 or 7
            return base - timedelta(days=back)
    if clock:
        return base if base <= now else base - timedelta(days=1)
    return None


def clean_text(raw: str) -> tuple[str, bool]:
    lines = [line.strip() for line in (raw or "").splitlines()]
    lines = [line for line in lines if line]
    replied = False
    if lines:
        head = lines[0].lower()
        for prefix in REPLY_PREFIX:
            if head.startswith(prefix):
                replied = True
                rest = lines[0][len(prefix):].strip()
                lines = ([rest] if rest else []) + lines[1:]
                break
    return "\n".join(lines).strip(), replied


def classify(item: dict, me: str) -> dict:
    author = (item.get("author") or "").strip().lstrip("/").lstrip("@").lower()
    mine = bool(me) and author == me.lower().lstrip("@")
    text, replied = clean_text(item.get("text") or "")
    images = [src for src in item.get("imgs") or [] if src and src.startswith("http")]
    server = SERVER_ID.search(item.get("server") or "")
    out = {"id": str(item.get("id") or "")[:64], "from_me": mine, "stamp": item.get("stamp") or "", "reply": replied,
           "server": server.group(1) if server else "", "failed": bool((item.get("warning") or "").strip())}
    if item.get("video"):
        out.update(kind="video_share", text=text, thumb=item.get("thumb") or "")
    elif images and not text:
        sticker = item.get("sticker") or "sticker" in images[0]
        out.update(kind="sticker" if sticker else "image", text="", image=images[0])
    elif text:
        out.update(kind="text", text=text)
    elif images:
        out.update(kind="image", text=text, image=images[0])
    else:
        out.update(kind="unsupported", text="")
    return out


def messages(raw: dict, me: str, now: datetime, limit: int = 40) -> dict:
    items = [classify(item, me) for item in (raw.get("items") or []) if item.get("id")]
    seen, unique = set(), []
    for item in items:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        when = parse_stamp(item.pop("stamp"), now)
        item["at"] = int(when.timestamp()) if when else None
        unique.append(item)
    handle = (raw.get("handle") or "").strip().lstrip("@")
    return {"handle": handle[:64], "items": unique[-limit:], "notice": (raw.get("notice") or "")[-700:]}


def delivered(items: list[dict]) -> list[dict]:
    return [row for row in items if not (row.get("from_me") and (row.get("failed") or not row.get("server")))]


def outcome(items: list[dict], before: set, text: str, notice: str) -> tuple[str, str]:
    wanted = " ".join((text or "").split())
    fresh = [row for row in items if row["id"] not in before and row["from_me"]]
    match = next((row for row in reversed(fresh) if " ".join((row.get("text") or "").split()) == wanted), None)
    if match is None and fresh:
        match = fresh[-1]
    if match is None:
        return "none", ""
    if match.get("failed"):
        return "failed", refused(notice) or "not_delivered"
    code = refused(notice)
    if code == "request_pending":
        return "failed", code
    if match.get("server"):
        return "sent", match["id"]
    return "pending", match["id"]


def chats(raw: list[dict]) -> list[dict]:
    out, seen = [], set()
    for item in raw or []:
        conv = str(item.get("id") or "")
        if not CONV.match(conv) or conv in seen:
            continue
        seen.add(conv)
        lines = [line.strip() for line in (item.get("rest") or "").splitlines() if line.strip()]
        name = (item.get("name") or (lines[0] if lines else "")).strip()
        body = [line for line in lines if line != name]
        date = body[-1] if body and (SHORT_DATE.search(body[-1]) or CLOCK.search(body[-1])) else ""
        preview = " ".join(line for line in body if line != date)
        out.append({"id": conv, "name": name[:120], "preview": preview[:200], "date": date[:40],
                    "unread": bool(item.get("unread")), "avatar": (item.get("avatar") or "")[:1000],
                    "sig": f"{preview[:200]}|{date}"})
    return out


def peer_of(conv: str, me_id: str) -> str:
    parts = conv.split(":")
    ids = [part for part in parts[2:] if part]
    others = [part for part in ids if part != me_id]
    return others[0] if others else ""


def blocked(text: str) -> str:
    lower = (text or "").lower()
    if any(word in lower for word in LOGIN_WORDS):
        return "logged_out"
    if any(word in lower for word in RATE_WORDS):
        return "rate_limited"
    return ""
