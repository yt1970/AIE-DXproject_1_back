from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ModuleNotFoundError:  # pragma: no cover - handled in get_storage_client
    boto3 = None  # type: ignore[assignment]
    BotoCoreError = ClientError = Exception  # type: ignore[assignment]

from app.core.settings import AppSettings, get_settings

logger = logging.getLogger(__name__)


class StorageError(RuntimeError):
    """Raised when the storage backend cannot persist a file."""


class StorageClient:
    """Abstract storage client interface."""

    def save(
        self,
        *,
        relative_path: str,
        data: bytes,
        content_type: Optional[str] = None,
    ) -> str:
        raise NotImplementedError


class LocalStorageClient(StorageClient):
    """Persist files on the local filesystem (useful for development/testing)."""

    def __init__(self, base_directory: Path) -> None:
        self.base_directory = base_directory

    def save(
        self,
        *,
        relative_path: str,
        data: bytes,
        content_type: Optional[str] = None,
    ) -> str:
        safe_path = _safe_join(self.base_directory, relative_path)
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_bytes(data)
        return str(safe_path)


class S3StorageClient(StorageClient):
    """Upload files to an S3 bucket."""

    def __init__(
        self,
        *,
        bucket: str,
        base_prefix: Optional[str],
        settings: AppSettings,
    ) -> None:
        if boto3 is None:
            raise StorageError(
                "boto3 dependency is required to use the S3 storage backend."
            )
        credentials = settings.aws_credentials
        self.bucket = bucket
        self.base_prefix = _normalize_prefix(base_prefix)

        session = boto3.session.Session(
            aws_access_key_id=credentials.get("access_key_id"),
            aws_secret_access_key=credentials.get("secret_access_key"),
            aws_session_token=credentials.get("session_token"),
            region_name=credentials.get("region"),
        )
        self.client = session.client("s3")

    def save(
        self,
        *,
        relative_path: str,
        data: bytes,
        content_type: Optional[str] = None,
    ) -> str:
        key = "/".join(
            part
            for part in (self.base_prefix, _normalize_key(relative_path))
            if part
        )
        try:
            extra_args = {"ContentType": content_type} if content_type else None
            self.client.put_object(
                Bucket=self.bucket, Key=key, Body=data, **(extra_args or {})
            )
        except (BotoCoreError, ClientError) as exc:
            logger.exception("Failed to upload file to S3: bucket=%s key=%s", self.bucket, key)
            raise StorageError(f"Failed to upload file to S3: {exc}") from exc

        return f"s3://{self.bucket}/{key}"


def _safe_join(base_directory: Path, relative_path: str) -> Path:
    """Join paths and prevent directory traversal outside of base_directory."""
    normalized = Path(_normalize_key(relative_path))
    full_path = base_directory.joinpath(normalized).resolve()
    if not str(full_path).startswith(str(base_directory.resolve())):
        raise StorageError("Attempted to write outside of the upload directory.")
    return full_path


def _normalize_prefix(prefix: Optional[str]) -> str:
    if not prefix:
        return ""
    return "/".join(part for part in prefix.strip("/").split("/") if part)


def _normalize_key(key: str) -> str:
    return "/".join(part for part in key.strip("/").split("/") if part)


@lru_cache(maxsize=1)
def get_storage_client(settings: Optional[AppSettings] = None) -> StorageClient:
    """Return a storage client configured for the current environment."""
    app_settings = settings or get_settings()
    storage_settings = app_settings.storage

    backend = storage_settings.backend
    if backend == "s3":
        if not storage_settings.s3_bucket:
            raise StorageError("S3 bucket is not configured.")
        return S3StorageClient(
            bucket=storage_settings.s3_bucket,
            base_prefix=storage_settings.base_prefix,
            settings=app_settings,
        )

    base_directory = storage_settings.local_directory_path
    base_directory.mkdir(parents=True, exist_ok=True)
    return LocalStorageClient(base_directory=base_directory)


def clear_storage_client_cache() -> None:
    """For testing: reset the cached storage client."""
    get_storage_client.cache_clear()  # type: ignore[attr-defined]
