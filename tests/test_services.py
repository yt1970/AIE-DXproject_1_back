from __future__ import annotations

import json
import textwrap
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

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
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _DummyClient:
    def __init__(self, *, expected_payload: dict[str, Any]) -> None:
        self.expected_payload = expected_payload
        self.captured_request: dict[str, Any] | None = None

    def __enter__(self) -> _DummyClient:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
        params: dict[str, str],
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
        ("categorization", {"category": "その他"}),
        ("risk_assessment", {"risk_level": "none", "is_safe": True}),
        ("full_analysis", {"summary": "mock"}),
    ],
)
def test_llm_client_mock_provider_deterministic(analysis_type: str, expected: dict[str, Any]) -> None:
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
                            "priority": "high",
                            "fix_difficulty": "none",
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
    assert result.priority == "high"
    assert result.fix_difficulty == "none"
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

    bucket, key = _split_s3_uri("s3://bucket-name/path/to.txt", default_bucket="fallback")
    assert bucket == "bucket-name"
    assert key == "path/to.txt"


def test_get_storage_client_local_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
# ---------------------------------------------------------------------------
# Summary computation tests
# ---------------------------------------------------------------------------
def _create_base_entities(db: Session) -> models.SurveyBatch:
    lecture = models.Lecture(
        id=1,
        name="AI入門",
        lecture_on=date(2024, 1, 1),
        academic_year=2024,
        term="Spring",
        session="1",
        instructor_name="Prof. AI",
    )
    db.add(lecture)
    db.flush()

    batch = models.SurveyBatch(
        id=1,
        lecture_id=lecture.id,
        uploaded_at=datetime.now(UTC),
    )
    db.add(batch)
    db.flush()
    return batch


def test_compute_and_upsert_summaries(db_session: Session) -> None:
    batch = _create_base_entities(db_session)

    responses = [
        models.SurveyResponse(
            survey_batch_id=batch.id,
            account_id=f"user-{idx}",
            score_satisfaction_overall=score,
            score_content_volume=score,
            score_content_understanding=score,
            score_content_announcement=score,
            score_instructor_overall=score,
            score_instructor_time=score,
            score_instructor_qa=score,
            score_instructor_speaking=score,
            score_self_preparation=score,
            score_self_motivation=score,
            score_self_future=score,
            score_recommend_friend=score + 5,
            student_attribute="ALL",
        )
        for idx, score in enumerate([3, 4, 5], start=1)
    ]
    db_session.add_all(responses)
    db_session.flush()

    comments = [
        models.ResponseComment(
            response_id=responses[idx].id,
            question_type="free_comment",
            comment_text=f"comment {idx}",
            llm_sentiment_type=sentiment,
            llm_category=category,
            llm_priority=priority,
        )
        for idx, (sentiment, category, priority) in enumerate(
            [
                ("positive", "講義内容", "medium"),
                ("negative", "講義資料", "high"),
                ("neutral", "運営", "low"),
            ],
            start=0,  # Start at 0 to match responses list indices
        )
    ]
    db_session.add_all(comments)
    db_session.commit()

    survey_summary, comment_counts = summary_module.compute_and_upsert_summaries(
        db_session, survey_batch=batch, version="preliminary"
    )

    assert survey_summary.response_count == 3
    # NOTE: comments_count and priority_comments_count removed from model
    assert comment_counts["comments_count"] == 3
    assert comment_counts["priority_comments_count"] == 2

    rows = db_session.query(models.CommentSummary).all()

    def _find(analysis_type: str, label: str) -> int:
        for r in rows:
            if r.analysis_type == analysis_type and r.label == label:
                return int(r.count or 0)
        return 0

    assert _find("sentiment", "positive") == 1
    assert _find("sentiment", "negative") == 1
    assert _find("category", "content") == 1
    assert _find("priority", "high") == 1


# ---------------------------------------------------------------------------
# Upload pipeline tests
# ---------------------------------------------------------------------------
class _DummyEnum:
    def __init__(self, value: str) -> None:
        self.value = value


class _DummyAnalysis:
    def __init__(self, *, sentiment_value: str, priority: str) -> None:
        self.category_normalized = _DummyEnum("content")
        self.summary = "要約"
        self.priority = priority
        self.priority_normalized = _DummyEnum(priority)
        self.fix_difficulty = "none"
        self.fix_difficulty_normalized = _DummyEnum("none")
        self.risk_level_normalized = _DummyEnum("low")
        self.sentiment_normalized = _DummyEnum(sentiment_value)
        self.is_abusive = False
        self.warnings: list[str] = []


def _create_upload_entities(
    db: Session,
) -> models.SurveyBatch:
    lecture = models.Lecture(
        id=2,
        name="強化学習",
        lecture_on=date(2024, 7, 1),
        academic_year=2024,
        term="Fall",
        session="1",
        instructor_name="Prof. RL",
    )
    db.add(lecture)
    db.flush()

    batch = models.SurveyBatch(
        id=2,
        lecture_id=lecture.id,
        uploaded_at=datetime.now(UTC),
    )
    db.add(batch)
    db.commit()
    return batch


def test_validate_csv_requires_comment_columns() -> None:
    with pytest.raises(upload_pipeline.CsvValidationError):
        upload_pipeline.validate_csv_or_raise(b"header1,header2\nvalue1,value2\n")


def test_analyze_and_store_comments(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    batch = _create_upload_entities(db_session)

    calls: list[bool] = []

    def _fake_analyze_comment(comment_text: str, *, skip_llm_analysis: bool, **kwargs: Any):
        calls.append(skip_llm_analysis)
        priority = "low" if skip_llm_analysis else "high"
        sentiment = "neutral" if skip_llm_analysis else "positive"
        return _DummyAnalysis(sentiment_value=sentiment, priority=priority)

    monkeypatch.setattr(upload_pipeline, "analyze_comment", _fake_analyze_comment)

    csv_content = textwrap.dedent(
        """\
            アカウントID,アカウント名,（任意）講義全体のコメント,【必須】講師へのメッセージ,本日の総合的な満足度を５段階で教えてください。,親しいご友人にこの講義の受講をお薦めしますか？,"本日の講義内容について５段階で教えてください。\n学習量は適切だった","本日の講義内容について５段階で教えてください。\n講義内容が十分に理解できた","本日の講義内容について５段階で教えてください。\n運営側のアナウンスが適切だった",本日の講師の総合的な満足度を５段階で教えてください。,"本日の講師について５段階で教えてください。\n授業時間を効率的に使っていた","本日の講師について５段階で教えてください。\n質問に丁寧に対応してくれた","本日の講師について５段階で教えてください。\n話し方や声の大きさが適切だった","ご自身について５段階で教えてください。\n事前に予習をした","ご自身について５段階で教えてください。\n意欲をもって講義に臨んだ","ご自身について５段階で教えてください。\n今回学んだことを学習や研究に生かせる"
            user-1,Student A,Great lecture!,Please invite again,5,10,5,5,5,5,5,5,5,5,5,5
            user-2,Student B,,Thanks,4,8,4,4,4,4,4,4,4,4,4,4
            """
    ).encode("utf-8")

    total_comments, processed_comments, total_responses = upload_pipeline.analyze_and_store_comments(
        db=db_session,
        survey_batch=batch,
        content_bytes=csv_content,
    )

    assert total_responses == 2
    assert total_comments == 3  # 二つのコメント列。1行は任意列が空
    assert processed_comments == 3

    # assert batch.total_responses == 2
    # assert batch.total_comments == 3

    stored_comments = db_session.query(models.ResponseComment).all()
    assert len(stored_comments) == 3
    assert any(comment.llm_priority == "low" for comment in stored_comments)
    assert any(comment.llm_priority == "high" for comment in stored_comments)

    # （任意）列のみLLM分析対象、必須列はスキップされる
    assert calls.count(False) == 1
    assert calls.count(True) == 2
