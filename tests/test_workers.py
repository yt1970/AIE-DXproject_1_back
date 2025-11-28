from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

from app.db import models


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


from app.workers import tasks


class DummyQuery:
    def __init__(self, session: "DummySession") -> None:
        self._session = session

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._session.survey_batch


class DummySession:
    def __init__(
        self,
        *,
        file_record: models.UploadedFile | None,
        survey_batch: models.SurveyBatch | None = None,
    ) -> None:
        self.file_record = file_record
        self.survey_batch = survey_batch
        self.closed = False
        self.commits = 0
        self.rolled_back = False
        self.added = []

    def get(self, _model, _pk):
        return self.file_record

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


def _make_uploaded_file() -> models.UploadedFile:
    return models.UploadedFile(
        id=1,
        course_name="Intro to Robotics",
        lecture_date=date(2024, 1, 1),
        lecture_number=1,
        academic_year="2024",
        period="Q1",
        status="QUEUED",
        s3_key="local://uploads/file.csv",
        uploaded_at=datetime.now(UTC),
        lecture_id=42,
    )


def _make_survey_batch(file_record: models.UploadedFile) -> models.SurveyBatch:
    batch = models.SurveyBatch(
        id=99,
        uploaded_file_id=file_record.id,
        lecture_id=file_record.lecture_id,
        course_name=file_record.course_name,
        lecture_date=file_record.lecture_date,
        lecture_number=file_record.lecture_number,
        academic_year=file_record.academic_year,
        period=file_record.period,
        status="QUEUED",
        uploaded_at=file_record.uploaded_at,
    )
    return batch


def _prepare_task_request():
    try:
        task_request = tasks.process_uploaded_file.request
        setattr(task_request, "retries", 0)
    except Exception:
        # Accessing the lazy Celery context can fail during unit tests; retries
        # are only read when handling StorageError, so default to zero.
        pass
    tasks.process_uploaded_file.max_retries = 3


def test_process_uploaded_file_returns_missing_when_file_not_found(monkeypatch):
    _prepare_task_request()
    session = DummySession(file_record=None)
    monkeypatch.setattr(tasks.db_session, "SessionLocal", lambda: session)

    dummy_storage = SimpleNamespace(load=lambda uri: b"")
    monkeypatch.setattr(tasks, "get_storage_client", lambda: dummy_storage)

    result = tasks.process_uploaded_file.run(file_id=12345)

    assert result == {"uploaded_file_id": 12345, "status": "missing"}
    assert session.closed


def test_process_uploaded_file_happy_path(monkeypatch):
    _prepare_task_request()
    file_record = _make_uploaded_file()
    survey_batch = _make_survey_batch(file_record)
    session = DummySession(file_record=file_record, survey_batch=survey_batch)
    monkeypatch.setattr(tasks.db_session, "SessionLocal", lambda: session)

    storage_client = SimpleNamespace(load=MagicMock(return_value=b"csv-bytes"))
    monkeypatch.setattr(tasks, "get_storage_client", lambda: storage_client)

    analyze_mock = MagicMock(return_value=(5, 5, 4))
    monkeypatch.setattr(tasks, "analyze_and_store_comments", analyze_mock)

    summary_mock = MagicMock()
    monkeypatch.setattr(tasks, "compute_and_upsert_summaries", summary_mock)

    result = tasks.process_uploaded_file.run(file_id=file_record.id)

    storage_client.load.assert_called_once_with(uri=file_record.s3_key)
    analyze_mock.assert_called_once()
    summary_mock.assert_called_once()
    assert result["status"] == tasks.COMPLETED_STATUS
    assert result["batch_id"] == survey_batch.id
    assert result["processed_comments"] == 5
    assert session.commits == 3
    assert session.closed
    assert file_record.status == tasks.COMPLETED_STATUS
    assert survey_batch.status == tasks.COMPLETED_STATUS
