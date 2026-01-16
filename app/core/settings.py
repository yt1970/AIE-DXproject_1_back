from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_dotenv_disabled = os.environ.get("APP_SKIP_DOTENV", "").lower() in {
    "1",
    "true",
    "yes",
}
COMMON_ENV_CONFIG = {
    "env_file": None if _dotenv_disabled else ".env",
    "env_file_encoding": "utf-8",
    "extra": "ignore",
}


class AWSSettings(BaseSettings):
    """AWS関連の認証情報を管理する設定。"""

    model_config = SettingsConfigDict(
        **COMMON_ENV_CONFIG,
        env_prefix="AWS_",
    )

    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    session_token: Optional[str] = None
    region: Optional[str] = None


class LLMSettings(BaseSettings):
    """LLM連携で利用する設定値。"""

    model_config = SettingsConfigDict(
        **COMMON_ENV_CONFIG,
        env_prefix="LLM_",
    )

    provider: str = "mock"
    api_base: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    api_version: Optional[str] = None
    organization: Optional[str] = None
    timeout_seconds: float = 15.0
    request_template: Optional[str] = None
    extra_headers: Dict[str, str] = Field(default_factory=dict)

    @field_validator("provider", mode="before")
    @classmethod
    def _parse_provider(cls, value: str) -> str:
        return value.lower().strip() if isinstance(value, str) else value

    @field_validator("timeout_seconds")
    @classmethod
    def _validate_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("LLM_TIMEOUT_SECONDS must be greater than zero.")
        return value

    @field_validator("extra_headers", mode="before")
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


class StorageSettings(BaseSettings):
    """ファイルアップロード処理で利用するストレージ設定。"""

    model_config = SettingsConfigDict(
        **COMMON_ENV_CONFIG,
        env_prefix="UPLOAD_",
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
            # 一部のPython版では親ディレクトリ欠如時にresolve()が例外を出すためフォールバック
            return path

    def ensure_local_directory(self) -> Path:
        """ローカルストレージ用ディレクトリを確実に作成し、解決済みパスを返す。"""
        path = self.local_directory_path
        path.mkdir(parents=True, exist_ok=True)
        return path


class CelerySettings(BaseSettings):
    """Celeryバックグラウンドワーカーの設定。"""

    model_config = SettingsConfigDict(
        **COMMON_ENV_CONFIG,
        env_prefix="CELERY_",
    )

    broker_url: str = "redis://localhost:6379/0"
    result_backend: Optional[str] = None
    task_default_queue: str = "aie_dxproject_analysis"
    task_always_eager: bool = False
    task_eager_propagates: bool = True
    task_default_retry_delay: float = 30.0
    task_max_retries: int = 3


class CognitoSettings(BaseSettings):
    """Cognito認証に関する設定。"""

    model_config = SettingsConfigDict(
        **COMMON_ENV_CONFIG,
        env_prefix="COGNITO_",
    )

    domain: Optional[str] = None
    client_id: Optional[str] = None
    logout_redirect_uri: Optional[str] = None


class AppSettings(BaseSettings):
    """アプリ全体の設定。機密情報は環境変数や .env から読み込む。"""

    model_config = SettingsConfigDict(
        **COMMON_ENV_CONFIG,
    )

    env: str = Field(default="development", alias="APP_ENV")
    title: str = Field(default="AIE-DXproject Backend", alias="API_TITLE")
    debug: bool = Field(default=False, alias="API_DEBUG")
    database_url: str = Field(
        default="sqlite:///./app_dev.sqlite3", alias="DATABASE_URL"
    )
    frontend_url: str = Field(
        default="http://localhost:3000", alias="FRONTEND_URL"
    )

    aws: AWSSettings = Field(default_factory=AWSSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    celery: CelerySettings = Field(default_factory=CelerySettings)
    cognito: CognitoSettings = Field(default_factory=CognitoSettings)

    @property
    def aws_credentials(self) -> Dict[str, str]:
        """boto3などに渡せる辞書形式の認証情報を返す。"""
        return {
            key: value
            for key, value in self.aws.model_dump().items()
            if value is not None
        }


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """アプリ設定をキャッシュ付きで取得する。"""
    return AppSettings()
