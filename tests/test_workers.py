from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

from app.db import models
from app.workers import tasks


def _install_boto3_stub():
    fake_session_module = ModuleType("boto3.session")
    fake_session_module.Session = lambda *args, **kwargs: SimpleNamespace(
        client=lambda *_a, **_kw: SimpleNamespace(
            put_object=lambda **_k: None,
            get_object=lambda **_k: {"Body": SimpleNamespace(read=lambda: b"")},
            delete_object=lambda **_k: None,
        )
    )

    fake_boto3 = ModuleType("boto3")
    fake_boto3.session = fake_session_module

    fake_botocore_exceptions = ModuleType("botocore.exceptions")
    fake_botocore_exceptions.BotoCoreError = Exception
    fake_botocore_exceptions.ClientError = Exception

    sys.modules.setdefault("boto3", fake_boto3)
    sys.modules.setdefault("boto3.session", fake_session_module)
    sys.modules.setdefault("botocore", ModuleType("botocore"))
    sys.modules["botocore"].exceptions = fake_botocore_exceptions
    sys.modules.setdefault("botocore.exceptions", fake_botocore_exceptions)


_install_boto3_stub()


class DummyQuery:
    def __init__(self, session: DummySession) -> None:
        self._session = session

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._session.survey_batch


class DummySession:
    def __init__(
        self,
        *,
        survey_batch: models.SurveyBatch | None = None,
    ) -> None:
        self.survey_batch = survey_batch
        self.closed = False
        self.commits = 0
        self.rolled_back = False
        self.added = []

    def get(self, _model, _pk):
        return self.survey_batch

    def query(self, _model):
        return DummyQuery(self)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rolled_back = True

    def flush(self):
        pass

    def close(self):
        self.closed = True


def _make_survey_batch() -> models.SurveyBatch:
    batch = models.SurveyBatch(
        id=99,
        lecture_id=42,
        uploaded_at=datetime.now(UTC),
    )
    return batch


def _prepare_task_request():
    try:
        task_request = tasks.process_uploaded_file.request
        task_request.retries = 0
    except Exception:
        # Accessing the lazy Celery context can fail during unit tests; retries
        # are only read when handling StorageError, so default to zero.
        pass
    tasks.process_uploaded_file.max_retries = 3


def test_process_uploaded_file_returns_missing_when_file_not_found(monkeypatch):
    _prepare_task_request()
    session = DummySession(survey_batch=None)
    monkeypatch.setattr(tasks.db_session, "SessionLocal", lambda: session)

    dummy_storage = SimpleNamespace(load=lambda uri: b"")
    monkeypatch.setattr(tasks, "get_storage_client", lambda: dummy_storage)

    result = tasks.process_uploaded_file.run(batch_id=12345, s3_key="mock_key")

    assert result == {"batch_id": 12345, "status": "missing"}
    assert session.closed


def test_process_uploaded_file_happy_path(monkeypatch):
    _prepare_task_request()
    survey_batch = _make_survey_batch()
    session = DummySession(survey_batch=survey_batch)
    monkeypatch.setattr(tasks.db_session, "SessionLocal", lambda: session)

    storage_client = SimpleNamespace(load=MagicMock(return_value=b"csv-bytes"))
    monkeypatch.setattr(tasks, "get_storage_client", lambda: storage_client)

    analyze_mock = MagicMock(return_value=(5, 5, 4))
    monkeypatch.setattr(tasks, "analyze_and_store_comments", analyze_mock)

    summary_mock = MagicMock()
    monkeypatch.setattr(tasks, "compute_and_upsert_summaries", summary_mock)

    result = tasks.process_uploaded_file.run(batch_id=survey_batch.id, s3_key="mock_key")

    storage_client.load.assert_called_once_with(uri="mock_key")
    analyze_mock.assert_called_once()
    summary_mock.assert_called_once()
    assert result["status"] == tasks.COMPLETED_STATUS
    assert result["batch_id"] == survey_batch.id
    assert result["processed_comments"] == 5
    assert session.commits == 2  # Removed status update commits
    assert session.closed
    # Status checks removed as status column is removed/not updated in task
