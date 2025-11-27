from __future__ import annotations

import json
import textwrap
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.services.llm_client as llm_client_module
from app.core import settings as settings_module
from app.db import models
from app.services import summary as summary_module
from app.services import upload_pipeline
from app.services.llm_client import LLMClient, LLMClientConfig
from app.services.storage import (
    LocalStorageClient,
    StorageError,
    _split_s3_uri,
    clear_storage_client_cache,
    get_storage_client,
)


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(name="db_session")
def fixture_db_session(tmp_path: Path) -> Session:
    db_path = tmp_path / "services.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}")
    models.Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# LLM client tests
# ---------------------------------------------------------------------------
class _DummyResponse:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Dict[str, Any]:
        return self._payload


class _DummyClient:
    def __init__(self, *, expected_payload: Dict[str, Any]) -> None:
        self.expected_payload = expected_payload
        self.captured_request: Dict[str, Any] | None = None

    def __enter__(self) -> "_DummyClient":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def post(
        self,
        url: str,
        *,
        json: Dict[str, Any],
        headers: Dict[str, str],
        params: Dict[str, str],
    ) -> _DummyResponse:
        self.captured_request = {
            "url": url,
            "json": json,
            "headers": headers,
            "params": params,
        }
        return _DummyResponse(self.expected_payload)


def test_llm_client_requires_comment_text() -> None:
    client = LLMClient(config=LLMClientConfig(provider="mock"))
    with pytest.raises(ValueError):
        client.analyze_comment("")


@pytest.mark.parametrize(
    "analysis_type,expected",
    [
        ("sentiment", {"sentiment": "neutral"}),
        ("importance", {"importance_level": "low", "importance_score": 0.1}),
        ("categorization", {"category": "その他", "tags": ["mock"]}),
        ("risk_assessment", {"risk_level": "none", "is_safe": True}),
        ("full_analysis", {"summary": "mock"}),
    ],
)
def test_llm_client_mock_provider_deterministic(
    analysis_type: str, expected: Dict[str, Any]
) -> None:
    client = LLMClient(config=LLMClientConfig(provider="mock"))
    result = client.analyze_comment("コメント", analysis_type=analysis_type)
    for key, value in expected.items():
        if key == "summary":
            assert isinstance(result.summary, str)
        else:
            assert getattr(result, key) == value


def test_llm_client_openai_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    expected_body = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "category": "講義内容",
                            "importance_level": "high",
                            "importance_score": 0.85,
                            "risk_level": "low",
                            "sentiment": "positive",
                            "summary": "短い要約",
                        }
                    )
                }
            }
        ]
    }
    dummy_client = _DummyClient(expected_payload=expected_body)

    def _fake_httpx_client(*args: Any, **kwargs: Any) -> _DummyClient:
        return dummy_client

    monkeypatch.setattr(llm_client_module.httpx, "Client", _fake_httpx_client)

    config = LLMClientConfig(
        provider="openai",
        base_url="https://example.com/v1/chat/completions",
        model="gpt-test",
        api_key="sk-test",
    )
    client = LLMClient(config=config)

    result = client.analyze_comment("素晴らしい講義でした。")

    assert result.category == "講義内容"
    assert result.importance_level == "high"
    assert result.importance_score == 0.85
    assert result.risk_level == "low"
    assert result.sentiment == "positive"
    assert result.summary == "短い要約"

    assert dummy_client.captured_request is not None
    assert dummy_client.captured_request["url"] == config.base_url
    assert dummy_client.captured_request["json"]["model"] == "gpt-test"
    assert dummy_client.captured_request["headers"]["Authorization"] == "Bearer sk-test"
    assert dummy_client.captured_request["params"] == {}


# ---------------------------------------------------------------------------
# Storage service tests
# ---------------------------------------------------------------------------
def test_local_storage_roundtrip(tmp_path: Path) -> None:
    client = LocalStorageClient(base_directory=tmp_path)
    uri = client.save(relative_path="lectures/file.txt", data=b"payload")
    assert uri.startswith("local://")

    loaded = client.load(uri=uri)
    assert loaded == b"payload"

    client.delete(uri=uri)
    with pytest.raises(StorageError):
        client.load(uri=uri)


def test_split_s3_uri_validation() -> None:
    with pytest.raises(StorageError):
        _split_s3_uri("invalid://bucket/key", default_bucket="fallback")

    bucket, key = _split_s3_uri(
        "s3://bucket-name/path/to.txt", default_bucket="fallback"
    )
    assert bucket == "bucket-name"
    assert key == "path/to.txt"


def test_get_storage_client_local_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UPLOAD_BACKEND", "local")
    monkeypatch.setenv("UPLOAD_LOCAL_DIRECTORY", str(tmp_path))
    settings_module.get_settings.cache_clear()
    clear_storage_client_cache()

    client = get_storage_client()
    assert isinstance(client, LocalStorageClient)
    client.save(relative_path="check.txt", data=b"ok")
    assert (tmp_path / "check.txt").exists()


# ---------------------------------------------------------------------------
# Summary computation tests
# ---------------------------------------------------------------------------
def _create_base_entities(db: Session) -> models.SurveyBatch:
    uploaded = models.UploadedFile(
        course_name="AI入門",
        lecture_date=date(2024, 1, 1),
        lecture_number=1,
        status="COMPLETED",
        upload_timestamp=datetime.now(UTC),
    )
    db.add(uploaded)
    db.flush()

    batch = models.SurveyBatch(
        file_id=uploaded.file_id,
        course_name=uploaded.course_name,
        lecture_date=uploaded.lecture_date,
        lecture_number=uploaded.lecture_number,
        status="READY",
        upload_timestamp=datetime.now(UTC),
    )
    db.add(batch)
    db.flush()
    return batch


def test_compute_and_upsert_summaries(db_session: Session) -> None:
    batch = _create_base_entities(db_session)

    responses = [
        models.SurveyResponse(
            file_id=batch.file_id,
            survey_batch_id=batch.id,
            row_index=idx,
            score_satisfaction_overall=score,
            score_recommend_to_friend=score + 5,
        )
        for idx, score in enumerate([3, 4, 5], start=1)
    ]
    db_session.add_all(responses)

    comments = [
        models.ResponseComment(
            file_id=batch.file_id,
            survey_batch_id=batch.id,
            question_text="（任意）講義全体のコメント",
            comment_text=f"comment {idx}",
            llm_sentiment=sentiment,
            llm_category=category,
            llm_importance_level=importance,
            analysis_version="preliminary",
        )
        for idx, (sentiment, category, importance) in enumerate(
            [
                ("positive", "講義内容", "medium"),
                ("negative", "講義資料", "high"),
                ("neutral", "運営", "low"),
            ],
            start=1,
        )
    ]
    db_session.add_all(comments)
    db_session.commit()

    survey_summary, comment_summary = summary_module.compute_and_upsert_summaries(
        db_session, survey_batch=batch, version="preliminary"
    )

    assert survey_summary.responses_count == 3
    assert survey_summary.comments_count == 3
    assert survey_summary.important_comments_count == 2

    assert comment_summary.sentiment_positive == 1
    assert comment_summary.sentiment_negative == 1
    assert comment_summary.category_lecture_content == 1
    assert comment_summary.importance_high == 1


# ---------------------------------------------------------------------------
# Upload pipeline tests
# ---------------------------------------------------------------------------
class _DummyEnum:
    def __init__(self, value: str) -> None:
        self.value = value


class _DummyAnalysis:
    def __init__(self, *, sentiment_value: str, importance_level: str) -> None:
        self.category_normalized = _DummyEnum("講義内容")
        self.summary = "要約"
        self.importance_level = importance_level
        self.importance_normalized = _DummyEnum(importance_level)
        self.importance_score = 0.8
        self.risk_level_normalized = _DummyEnum("low")
        self.sentiment_normalized = _DummyEnum(sentiment_value)
        self.warnings: List[str] = []


def _create_upload_entities(
    db: Session,
) -> Tuple[models.UploadedFile, models.SurveyBatch]:
    uploaded = models.UploadedFile(
        course_name="強化学習",
        lecture_date=date(2024, 7, 1),
        lecture_number=1,
        status="PROCESSING",
        upload_timestamp=datetime.now(UTC),
    )
    db.add(uploaded)
    db.flush()

    batch = models.SurveyBatch(
        file_id=uploaded.file_id,
        course_name=uploaded.course_name,
        lecture_date=uploaded.lecture_date,
        lecture_number=uploaded.lecture_number,
        status="PROCESSING",
        upload_timestamp=datetime.now(UTC),
    )
    db.add(batch)
    db.commit()
    return uploaded, batch


def test_validate_csv_requires_comment_columns() -> None:
    with pytest.raises(upload_pipeline.CsvValidationError):
        upload_pipeline.validate_csv_or_raise(b"header1,header2\nvalue1,value2\n")


def test_analyze_and_store_comments(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploaded, batch = _create_upload_entities(db_session)

    calls: List[bool] = []

    def _fake_analyze_comment(
        comment_text: str, *, skip_llm_analysis: bool, **kwargs: Any
    ):
        calls.append(skip_llm_analysis)
        importance = "low" if skip_llm_analysis else "high"
        sentiment = "neutral" if skip_llm_analysis else "positive"
        return _DummyAnalysis(sentiment_value=sentiment, importance_level=importance)

    monkeypatch.setattr(upload_pipeline, "analyze_comment", _fake_analyze_comment)

    csv_content = textwrap.dedent(
        """\
        アカウントID,アカウント名,（任意）講義全体のコメント,【必須】講師へのメッセージ,本日の総合的な満足度を５段階で教えてください。,親しいご友人にこの講義の受講をお薦めしますか？
        user-1,Student A,Great lecture!,Please invite again,5,10
        user-2,Student B,,Thanks,4,8
        """
    ).encode("utf-8")

    total_comments, processed_comments, total_responses = (
        upload_pipeline.analyze_and_store_comments(
            db=db_session,
            file_record=uploaded,
            survey_batch=batch,
            content_bytes=csv_content,
        )
    )

    assert total_responses == 2
    assert total_comments == 3  # 二つのコメント列。1行は任意列が空
    assert processed_comments == 3

    assert batch.total_responses == 2
    assert batch.total_comments == 3

    stored_comments = db_session.query(models.ResponseComment).all()
    assert len(stored_comments) == 3
    assert any(comment.llm_importance_level == "low" for comment in stored_comments)
    assert any(comment.llm_importance_level == "high" for comment in stored_comments)

    # （任意）列のみLLM分析対象、必須列はスキップされる
    assert calls.count(False) == 1
    assert calls.count(True) == 2
