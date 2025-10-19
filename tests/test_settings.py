from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest

from app.core import settings as settings_module


@pytest.fixture(autouse=True)
def clear_settings_cache():
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()


def test_settings_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_TITLE", "Prod Backend")
    monkeypatch.setenv("API_DEBUG", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.com/db")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("LLM_EXTRA_HEADERS", '{"X-Test": "yes"}')

    settings = settings_module.get_settings()

    assert settings.env == "production"
    assert settings.title == "Prod Backend"
    assert settings.debug is True
    assert settings.database_url == "postgresql://example.com/db"
    assert settings.llm.provider == "openai"
    assert settings.llm.timeout_seconds == 20
    assert settings.llm.extra_headers == {"X-Test": "yes"}


def test_aws_credentials_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")

    settings = settings_module.get_settings()

    expected: Dict[str, str] = {
        "access_key_id": "test-access",
        "secret_access_key": "test-secret",
        "region": "ap-northeast-1",
    }

    assert settings.aws_credentials == expected


def test_storage_settings_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    uploads_dir = tmp_path / "uploads"
    monkeypatch.setenv("UPLOAD_BACKEND", "LOCAL")
    monkeypatch.setenv("UPLOAD_LOCAL_DIRECTORY", str(uploads_dir))

    settings = settings_module.get_settings()

    assert settings.storage.backend == "local"
    assert settings.storage.base_prefix == "uploads"
    assert settings.storage.local_directory_path == uploads_dir.resolve()


def test_storage_settings_s3_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPLOAD_BACKEND", "s3")
    monkeypatch.setenv("UPLOAD_BASE_PREFIX", "custom/uploads/")
    monkeypatch.setenv("UPLOAD_S3_BUCKET", "my-upload-bucket")

    settings = settings_module.get_settings()

    assert settings.storage.backend == "s3"
    assert settings.storage.base_prefix == "custom/uploads"
    assert settings.storage.s3_bucket == "my-upload-bucket"
