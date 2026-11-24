"""Object storage for large, rarely read artefacts: full decision traces, eval reports, the router model.

Production: S3. Local compose: SeaweedFS (same API, `S3_ENDPOINT_URL`). Tests and no-infra dev:
a directory on disk. The database keeps only the key.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


class ObjectStore(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    def get_bytes(self, key: str) -> bytes | None: ...


def put_json(store: ObjectStore, key: str, obj: Any) -> None:
    store.put_bytes(key, json.dumps(obj, ensure_ascii=False).encode(), "application/json")


def get_json(store: ObjectStore, key: str) -> Any | None:
    data = store.get_bytes(key)
    return json.loads(data) if data is not None else None


class LocalStore:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError(f"key escapes the store: {key!r}")
        return path

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)  # atomic: readers never see half a file

    def get_bytes(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.exists() else None


class S3Store:
    def __init__(self, bucket: str, endpoint_url: str | None = None, region: str = "us-east-1"):
        import boto3

        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)

    def ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get_bytes(self, key: str) -> bytes | None:
        from botocore.exceptions import ClientError

        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise
