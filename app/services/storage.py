from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ModuleNotFoundError:  # pragma: no cover - get_storage_clientで処理される
    boto3 = None  # type: ignore[assignment]
    BotoCoreError = ClientError = Exception  # type: ignore[assignment]

from app.core.settings import AppSettings, get_settings

logger = logging.getLogger(__name__)


class StorageError(RuntimeError):
    """ストレージバックエンドがファイルを永続化できない場合に送出される。"""


class StorageClient:
    """抽象ストレージクライアントインターフェース。"""

    def save(
        self,
        *,
        relative_path: str,
        data: bytes,
        content_type: Optional[str] = None,
    ) -> str:
        raise NotImplementedError

    def load(self, *, uri: str) -> bytes:
        raise NotImplementedError

    def delete(self, *, uri: str) -> None:
        raise NotImplementedError


class LocalStorageClient(StorageClient):
    """ローカルファイルシステムへ保存するクライアント（開発・テスト向け）。"""

    def __init__(self, base_directory: Path) -> None:
        self.base_directory = base_directory

    def save(
        self,
        *,
        relative_path: str,
        data: bytes,
        content_type: Optional[str] = None,
    ) -> str:
        normalized_key = _normalize_key(relative_path)
        safe_path = _safe_join(self.base_directory, normalized_key)
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_bytes(data)
        return f"local://{normalized_key}"

    def load(self, *, uri: str) -> bytes:
        scheme, key = _split_uri(uri)
        if scheme != "local":
            raise StorageError(
                f"Unsupported URI scheme '{scheme}' for LocalStorageClient."
            )
        safe_path = _safe_join(self.base_directory, key)
        try:
            return safe_path.read_bytes()
        except FileNotFoundError as exc:
            raise StorageError(f"Stored file not found: {key}") from exc

    def delete(self, *, uri: str) -> None:
        scheme, key = _split_uri(uri)
        if scheme != "local":
            raise StorageError(
                f"Unsupported URI scheme '{scheme}' for LocalStorageClient."
            )
        safe_path = _safe_join(self.base_directory, key)
        try:
            safe_path.unlink(missing_ok=True)
        except Exception as exc:  # pragma: no cover
            logger.exception("Failed to delete local file: %s", safe_path)
            raise StorageError(f"Failed to delete local file: {exc}") from exc


class S3StorageClient(StorageClient):
    """S3バケットへファイルをアップロードするクライアント。"""

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
            part for part in (self.base_prefix, _normalize_key(relative_path)) if part
        )
        try:
            extra_args = {"ContentType": content_type} if content_type else None
            self.client.put_object(
                Bucket=self.bucket, Key=key, Body=data, **(extra_args or {})
            )
        except (BotoCoreError, ClientError) as exc:
            logger.exception(
                "Failed to upload file to S3: bucket=%s key=%s", self.bucket, key
            )
            raise StorageError(f"Failed to upload file to S3: {exc}") from exc

        return f"s3://{self.bucket}/{key}"

    def load(self, *, uri: str) -> bytes:
        bucket, key = _split_s3_uri(uri, default_bucket=self.bucket)
        try:
            response = self.client.get_object(Bucket=bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            logger.exception(
                "Failed to download file from S3: bucket=%s key=%s", bucket, key
            )
            raise StorageError(f"Failed to download file from S3: {exc}") from exc

        body = response.get("Body")
        if body is None:
            raise StorageError("S3 object body is empty.")
        return body.read()

    def delete(self, *, uri: str) -> None:
        bucket, key = _split_s3_uri(uri, default_bucket=self.bucket)
        try:
            self.client.delete_object(Bucket=bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            logger.exception(
                "Failed to delete file from S3: bucket=%s key=%s", bucket, key
            )
            raise StorageError(f"Failed to delete file from S3: {exc}") from exc


def _safe_join(base_directory: Path, relative_path: str) -> Path:
    """パスを連結し、base_directoryの外へディレクトリトラバーサルされるのを防ぐ。"""
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


def _split_uri(uri: str) -> Tuple[str, str]:
    if "://" not in uri:
        raise StorageError(f"Invalid storage URI: {uri}")
    scheme, _, key = uri.partition("://")
    return scheme, _normalize_key(key)


def _split_s3_uri(uri: str, *, default_bucket: str) -> Tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme and parsed.scheme != "s3":
        raise StorageError(f"Invalid S3 URI scheme: {parsed.scheme}")
    bucket = parsed.netloc or default_bucket
    if not bucket:
        raise StorageError("S3 bucket is not specified in URI or configuration.")
    key = _normalize_key(parsed.path)
    if not key:
        raise StorageError("S3 object key cannot be empty.")
    return bucket, key


@lru_cache(maxsize=1)
def get_storage_client(settings: Optional[AppSettings] = None) -> StorageClient:
    """現在の環境設定に応じたストレージクライアントを返す。"""
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

    base_directory = storage_settings.ensure_local_directory()
    return LocalStorageClient(base_directory=base_directory)


def clear_storage_client_cache() -> None:
    """テスト向け: キャッシュ済みのストレージクライアントをリセットする。"""
    get_storage_client.cache_clear()  # type: ignore[attr-defined]
