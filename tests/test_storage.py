from __future__ import annotations

from pathlib import Path

import pytest

from app.core import settings as settings_module
from app.services.storage import (
    StorageError,
    clear_storage_client_cache,
    get_storage_client,
)


@pytest.fixture(autouse=True)
def reset_storage_cache() -> None:
    settings_module.get_settings.cache_clear()
    clear_storage_client_cache()
    yield
    clear_storage_client_cache()
    settings_module.get_settings.cache_clear()


def test_local_storage_saves_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UPLOAD_BACKEND", "local")
    monkeypatch.setenv("UPLOAD_LOCAL_DIRECTORY", str(tmp_path))

    client = get_storage_client()
    location = client.save(
        relative_path="nested/file.txt",
        data=b"hello storage",
        content_type="text/plain",
    )

    saved_path = Path(location)
    assert saved_path.exists()
    assert saved_path.read_bytes() == b"hello storage"
    assert saved_path.samefile(tmp_path / "nested" / "file.txt")


def test_s3_backend_requires_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPLOAD_BACKEND", "s3")

    with pytest.raises(StorageError):
        get_storage_client()
