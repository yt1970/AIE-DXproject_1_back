from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from app.core import settings as settings_module

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"

EXPECTED_TABLES = {
    "lectures",
    "uploaded_files",
    "survey_batches",
    "survey_responses",
    "response_comments",
    "lecture_metrics",
    "survey_summaries",
    "comment_summaries",
    "score_distributions",
}


@pytest.fixture
def alembic_test_config(tmp_path, monkeypatch):
    db_path = tmp_path / "alembic_test.sqlite3"
    db_url = f"sqlite:///{db_path}"

    monkeypatch.setenv("DATABASE_URL", db_url)
    settings_module.get_settings.cache_clear()

    cfg = Config(str(ALEMBIC_INI))

    yield cfg, db_url

    settings_module.get_settings.cache_clear()


def _inspect_tables(db_url: str) -> set[str]:
    engine = create_engine(db_url)
    try:
        inspector = inspect(engine)
        return set(inspector.get_table_names())
    finally:
        engine.dispose()


def test_baseline_upgrade_creates_expected_tables(alembic_test_config):
    cfg, db_url = alembic_test_config

    command.upgrade(cfg, "head")

    tables = _inspect_tables(db_url)
    assert EXPECTED_TABLES <= tables


def test_baseline_downgrade_removes_tables(alembic_test_config):
    cfg, db_url = alembic_test_config

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    tables = _inspect_tables(db_url)
    assert EXPECTED_TABLES.isdisjoint(tables)
