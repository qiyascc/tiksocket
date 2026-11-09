from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

KEY_ENV = "TIKSOCKET_KEY"


def generate_key() -> str:
    return Fernet.generate_key().decode()


@dataclass
class AuthState:
    folder: Path
    key: str | None = None
    _fernet: Fernet | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.folder = Path(self.folder)
        self.key = self.key or os.environ.get(KEY_ENV) or self._stored_key()
        self._fernet = Fernet(self.key.encode()) if self.key else None

    def _stored_key(self) -> str | None:
        path = self.folder / ".key"
        if path.exists():
            return path.read_text(encoding="utf-8").strip() or None
        return None

    def ensure_key(self) -> None:
        if self._fernet is not None:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        self.key = generate_key()
        path = self.folder / ".key"
        path.write_text(self.key, encoding="utf-8")
        os.chmod(path, 0o600)
        self._fernet = Fernet(self.key.encode())

    @property
    def exists(self) -> bool:
        return (self.folder / "state.bin").exists()

    def _write(self, name: str, data: bytes) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.folder / f"{name}.tmp"
        tmp.write_bytes(data)
        os.chmod(tmp, 0o600)
        tmp.replace(self.folder / name)

    def save_state(self, state: dict) -> None:
        self.ensure_key()
        self._write("state.bin", self._fernet.encrypt(json.dumps(state).encode()))

    def load_state(self) -> dict | None:
        path = self.folder / "state.bin"
        if not path.exists() or self._fernet is None:
            return None
        try:
            return json.loads(self._fernet.decrypt(path.read_bytes()))
        except (InvalidToken, ValueError):
            return None

    def save_profile(self, profile: dict) -> None:
        self._write("profile.json", json.dumps(profile, ensure_ascii=False).encode())

    def load_profile(self) -> dict:
        try:
            return json.loads((self.folder / "profile.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def load_json(self, name: str) -> dict:
        try:
            data = json.loads((self.folder / name).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_json(self, name: str, data: dict) -> None:
        self._write(name, json.dumps(data, ensure_ascii=False).encode())

    def debug_folder(self) -> Path:
        path = self.folder / "debug"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def clear(self) -> None:
        for name in ("state.bin", "profile.json", "sent.json", "seen.json"):
            try:
                (self.folder / name).unlink()
            except FileNotFoundError:
                pass

    def remove(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)

    def touch(self) -> None:
        self._write("last_used", str(int(time.time())).encode())


def use_multi_file_auth_state(folder: str | os.PathLike, key: str | None = None) -> AuthState:
    return AuthState(Path(folder), key)
