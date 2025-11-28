from __future__ import annotations

import importlib
import os
from types import ModuleType

import pytest
from sqlalchemy import inspect, text

os.environ.setdefault("PYTHON_DOTENV_SKIP_DOTENV", "1")
os.environ.setdefault("APP_SKIP_DOTENV", "1")

import app.db.init_db as init_db_module
import app.db.session as session_module
from app.core import settings as settings_module


@pytest.fixture
def session_reloader(monkeypatch, tmp_path):
    """
    Reload app.db.session with a dedicated SQLite database file so tests
    can operate without touching the real application database.
    """

    def _reload(db_name: str) -> tuple[ModuleType, str]:
        db_path = tmp_path / db_name
        db_url = f"sqlite:///{db_path}"
        monkeypatch.setenv("DATABASE_URL", db_url)
        settings_module.get_settings.cache_clear()
        reloaded_session = importlib.reload(session_module)
        return reloaded_session, db_url

    yield _reload

    settings_module.get_settings.cache_clear()
    importlib.reload(session_module)
    importlib.reload(init_db_module)


def test_get_db_yields_working_session(session_reloader):
    session_mod, _ = session_reloader("session_test.sqlite3")

    db_generator = session_mod.get_db()
    db_session = next(db_generator)

    result = db_session.execute(text("SELECT 1")).scalar()
    assert result == 1

    db_generator.close()

    # Ensure a new session can still be created after closing the previous one.
    next_session_gen = session_mod.get_db()
    next_session = next(next_session_gen)
    assert next_session.bind.url.database.endswith("session_test.sqlite3")
    next_session_gen.close()


def test_init_db_creates_expected_tables(session_reloader):
    session_mod, _ = session_reloader("init_db_test.sqlite3")
    init_module = importlib.reload(init_db_module)

    init_module.init_db()

    inspector = inspect(session_mod.engine)
    tables = set(inspector.get_table_names())

    expected_tables = {
        "uploaded_files",
        "survey_batches",
        "survey_responses",
        "response_comments",
        "lectures",
        "lecture_metrics",
        "survey_summaries",
        "comment_summaries",
        "score_distributions",
    }

    assert expected_tables <= tables
