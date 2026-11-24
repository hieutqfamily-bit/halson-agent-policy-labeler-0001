"""Where API keys live. A port with three adapters, picked by SECRETS_BACKEND (bootstrap.py):

    env  read-only: environment variables / .env (the 12-factor default; nothing stored by the app)
    db   local and compose: keys entered on the Settings page, encrypted with a master key
         (Fernet: AES-128-CBC + HMAC-SHA256) before they reach the database. The master key
         comes from SECRETS_KEY, or is generated once into data/secrets.key (mode 0600,
         gitignored), which every container sees through the ./data mount.
    aws  production: AWS Secrets Manager (KMS-encrypted, IAM-scoped, audited by CloudTrail).
         Task roles get secretsmanager:GetSecretValue on the `policy-labeler/*` prefix only.

Every adapter falls back to the environment, so a key in .env always works. The API never
returns a key: only where it came from and its last four characters (see DESIGN.md §6).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Protocol

from labeler.errors import InvalidInput
from labeler.infra.db import DB

# The only secrets the app knows. Anything else is rejected, so the store cannot become a
# general-purpose key-value bucket written from the UI.
KNOWN = {
    "ANTHROPIC_API_KEY": "Claude API",
    "OPENAI_API_KEY": "OpenAI",
    "COMPAT_API_KEY": "OpenAI-compatible endpoint (Gemini, Groq, OpenRouter, ...)",
}
CACHE_S = 5.0


def _hint(value: str) -> str:
    return "…" + value[-4:] if len(value) >= 8 else "…"


class SecretStore(Protocol):
    backend: str

    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> bool: ...
    def describe(self, name: str) -> dict[str, Any]: ...


def _check(name: str) -> None:
    if name not in KNOWN:
        raise InvalidInput(f"unknown secret {name!r}; known: {', '.join(KNOWN)}")


class EnvSecrets:
    backend = "env"

    def get(self, name: str) -> str | None:
        return os.environ.get(name) or None

    def set(self, name: str, value: str) -> None:
        raise InvalidInput("SECRETS_BACKEND=env is read-only: put the key in .env or the environment")

    def delete(self, name: str) -> bool:
        raise InvalidInput("SECRETS_BACKEND=env is read-only")

    def describe(self, name: str) -> dict[str, Any]:
        v = self.get(name)
        return {"name": name, "set": bool(v), "source": "environment" if v else None, "hint": _hint(v) if v else None}


class _Cached:
    """Shared by the stores that call out: workers read a key per model call, so cache briefly."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, str | None]] = {}

    def _cached(self, name: str, load) -> str | None:
        t = time.monotonic()
        hit = self._cache.get(name)
        if hit and t - hit[0] < CACHE_S:
            return hit[1]
        v = load()
        self._cache[name] = (t, v)
        return v

    def _forget(self, name: str) -> None:
        self._cache.pop(name, None)


class EncryptedDbSecrets(_Cached):
    backend = "db"

    def __init__(self, db: DB, master_key: str = "", key_file: Path | None = None):
        super().__init__()
        from cryptography.fernet import Fernet

        self.db = db
        key = master_key.encode() if master_key else self._key_from_file(key_file)
        self.fernet = Fernet(key)

    @staticmethod
    def _key_from_file(path: Path | None) -> bytes:
        from cryptography.fernet import Fernet

        if path is None:
            raise InvalidInput("set SECRETS_KEY or give a key file")
        if path.exists():
            return path.read_bytes().strip()
        path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:  # another container created it first
            return path.read_bytes().strip()
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        return key

    def get(self, name: str) -> str | None:
        def load() -> str | None:
            row = self.db.get_secret_row(name)
            if row:
                return self.fernet.decrypt(row["ciphertext"].encode()).decode()
            return os.environ.get(name) or None

        return self._cached(name, load)

    def set(self, name: str, value: str) -> None:
        _check(name)
        value = value.strip()
        if not value:
            raise InvalidInput("empty key")
        self.db.put_secret_row(name, self.fernet.encrypt(value.encode()).decode(), _hint(value))
        self._forget(name)

    def delete(self, name: str) -> bool:
        _check(name)
        self._forget(name)
        return self.db.delete_secret_row(name)

    def describe(self, name: str) -> dict[str, Any]:
        row = self.db.get_secret_row(name)
        if row:
            return {"name": name, "set": True, "source": "settings (encrypted in the database)", "hint": row["hint"]}
        v = os.environ.get(name)
        return {"name": name, "set": bool(v), "source": "environment" if v else None, "hint": _hint(v) if v else None}


class AwsSecrets(_Cached):
    backend = "aws"

    def __init__(self, prefix: str, region: str, endpoint_url: str | None = None):
        super().__init__()
        import boto3

        self.client = boto3.client("secretsmanager", region_name=region, endpoint_url=endpoint_url)
        self.prefix = prefix

    def _id(self, name: str) -> str:
        return f"{self.prefix}{name}"

    def get(self, name: str) -> str | None:
        def load() -> str | None:
            try:
                return self.client.get_secret_value(SecretId=self._id(name))["SecretString"]
            except self.client.exceptions.ResourceNotFoundException:
                return os.environ.get(name) or None

        return self._cached(name, load)

    def set(self, name: str, value: str) -> None:
        _check(name)
        try:
            self.client.put_secret_value(SecretId=self._id(name), SecretString=value.strip())
        except self.client.exceptions.ResourceNotFoundException:
            self.client.create_secret(Name=self._id(name), SecretString=value.strip())
        self._forget(name)

    def delete(self, name: str) -> bool:
        _check(name)
        self._forget(name)
        try:
            self.client.delete_secret(SecretId=self._id(name), RecoveryWindowInDays=7)
            return True
        except self.client.exceptions.ResourceNotFoundException:
            return False

    def describe(self, name: str) -> dict[str, Any]:
        v = self.get(name)
        src = None
        if v:
            try:
                self.client.describe_secret(SecretId=self._id(name))
                src = "AWS Secrets Manager"
            except self.client.exceptions.ResourceNotFoundException:
                src = "environment"
        return {"name": name, "set": bool(v), "source": src, "hint": _hint(v) if v else None}
