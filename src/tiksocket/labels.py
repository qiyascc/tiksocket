from __future__ import annotations

import re

LABELS = {
    "publish": ["post", "publish", "veröffentlichen", "veroeffentlichen", "publicar", "publier", "pubblica", "paylaş",
                "опубликовать", "paylas"],
    "confirm": ["post now", "publish now", "confirm", "continue", "bestätigen", "fortfahren", "indi paylaş",
                "опубликовать сейчас"],
    "published": ["your video has been posted", "your post has been published", "video posted", "video published",
                  "post published", "veröffentlicht"],
    "failed": ["couldn't post", "could not post", "failed to post", "post failed", "something went wrong",
               "fehlgeschlagen", "nicht möglich"],
    "failed_upload": ["couldn't upload", "upload failed", "unsupported format", "video is too short",
                      "file is too large"],
    "content_check": ["content check lite", "content check", "short content check", "copyright check",
                      "inhaltsprüfung"],
    "got_it": ["got it", "ok", "verstanden"],
    "later": ["not now", "later", "skip", "später"],
    "close": ["close", "schließen"],
    "cancel": ["cancel", "abbrechen", "iptal", "отмена"],
    "content_prompt": ["turn on automatic content checks", "automatic content checks", "new editing features"],
    "photos": ["photos", "photo", "fotoğraflar", "fotolar", "фото", "fotos"],
    "add_sound": ["add sound", "səs əlavə et", "ses ekle", "добавить звук", "sound hinzufügen"],
    "use": ["use", "istifadə et", "kullan", "использовать", "verwenden"],
    "search_sounds": ["search sounds", "səs axtar", "ses ara", "поиск звуков"],
    "videos": ["videos", "video"],
}


def terms(key: str) -> list[str]:
    return list(LABELS.get(key, []))


def pattern(key: str) -> re.Pattern:
    values = sorted(terms(key), key=len, reverse=True)
    return re.compile("|".join(re.escape(v) for v in values), re.I)


def exact(key: str) -> re.Pattern:
    values = sorted(terms(key), key=len, reverse=True)
    return re.compile(r"^\s*(" + "|".join(re.escape(v) for v in values) + r")\s*$", re.I)


def matches(text: str, key: str) -> bool:
    return bool(pattern(key).search(text or ""))
