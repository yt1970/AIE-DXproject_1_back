from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class AWSSettings(BaseSettings):
    """AWS関連の認証情報を管理する設定。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AWS_",
        extra="ignore",
    )

    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    session_token: Optional[str] = None
    region: Optional[str] = None


class LLMSettings(BaseSettings):
    """LLM連携で利用する設定値。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LLM_",
        extra="ignore",
    )

    provider: str = "mock"
    api_base: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_version: Optional[str] = None
    organization: Optional[str] = None
    timeout_seconds: float = 15.0
    request_template: Optional[str] = None
    extra_headers: Optional[str | Dict[str, str]] = None

    @classmethod
    def _parse_provider(cls, value: str) -> str:
        return value.lower().strip()

    @classmethod
    def _parse_extra_headers(
        cls, value: Optional[str | Dict[str, str]]
    ) -> Dict[str, str]:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items()}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "LLM_EXTRA_HEADERS must be a JSON object string"
                ) from exc
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items()}
            raise ValueError("LLM_EXTRA_HEADERS must decode to a JSON object")
        raise ValueError("LLM_EXTRA_HEADERS must be a JSON object or empty.")

    def model_post_init(self, __context: Dict[str, object]) -> None:
        # 正規化処理をここで実施
        object.__setattr__(self, "provider", self._parse_provider(self.provider))
        if self.timeout_seconds <= 0:
            raise ValueError("LLM_TIMEOUT_SECONDS must be greater than zero.")
        try:
            headers = self._parse_extra_headers(self.extra_headers)
        except ValueError as exc:
            logger.warning("%s", exc)
            headers = {}
        object.__setattr__(self, "extra_headers", headers)


class StorageSettings(BaseSettings):
    """ファイルアップロード処理で利用するストレージ設定。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="UPLOAD_",
        extra="ignore",
    )

    backend: str = "local"
    s3_bucket: Optional[str] = None
    base_prefix: Optional[str] = "uploads"
    local_directory: str = "./var/uploads"

    def model_post_init(self, __context: Dict[str, object]) -> None:
        backend = (self.backend or "local").strip().lower()
        if backend not in {"local", "s3"}:
            logger.warning(
                "Unsupported upload backend '%s'; falling back to 'local'.",
                self.backend,
            )
            backend = "local"
        object.__setattr__(self, "backend", backend)

        normalized_prefix = ""
        if self.base_prefix:
            normalized_prefix = "/".join(
                part for part in self.base_prefix.strip("/").split("/") if part
            )
        object.__setattr__(self, "base_prefix", normalized_prefix)

    @property
    def local_directory_path(self) -> Path:
        path = Path(self.local_directory).expanduser()
        try:
            return path.resolve()
        except FileNotFoundError:
            # resolve() raises if a parent is missing on some Python versions; fallback.
            return path


class AppSettings(BaseSettings):
    """アプリ全体の設定。機密情報は環境変数や .env から読み込む。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = Field(default="development", alias="APP_ENV")
    title: str = Field(default="AIE-DXproject Backend", alias="API_TITLE")
    debug: bool = Field(default=False, alias="API_DEBUG")
    database_url: str = Field(
        default="sqlite:///./app_dev.sqlite3", alias="DATABASE_URL"
    )

    aws: AWSSettings = Field(default_factory=AWSSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)

    @property
    def aws_credentials(self) -> Dict[str, str]:
        """boto3などに渡せる辞書形式の認証情報を返す。"""
        return {
            key: value
            for key, value in self.aws.model_dump().items()
            if value is not None
        }


@lru_cache
def get_settings() -> AppSettings:
    """アプリ設定をキャッシュ付きで取得する。"""
    return AppSettings()
