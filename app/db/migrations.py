from __future__ import annotations

import logging
from typing import List, Sequence, Set

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def apply_migrations(engine: Engine) -> None:
    """Ensure required columns exist on existing databases."""
    if engine is None:
        logger.warning("No database engine provided; skipping migrations.")
        return

    inspector = inspect(engine)
    table_names: Sequence[str] = inspector.get_table_names()

    statements: List[str] = []

    if "comment" in table_names:
        comment_columns: Set[str] = {
            column["name"] for column in inspector.get_columns("comment")
        }
        statements.extend(_build_comment_migrations(comment_columns))
    else:
        logger.info("Table 'comment' not found; skipping LLM column migration.")

    if "uploaded_file" in table_names:
        uploaded_columns: Set[str] = {
            column["name"] for column in inspector.get_columns("uploaded_file")
        }
        statements.extend(_build_uploaded_file_migrations(uploaded_columns))
    else:
        logger.info(
            "Table 'uploaded_file' not found; skipping storage column migration."
        )

    if not statements:
        logger.debug("No schema migrations required.")
        return

    with engine.begin() as connection:
        for statement in statements:
            logger.info("Applying migration: %s", statement)
            connection.execute(text(statement))

    logger.info("Applied %d migration statements.", len(statements))


def _build_comment_migrations(existing_columns: Set[str]) -> List[str]:
    """Build ALTER TABLE statements for missing columns."""
    statements: List[str] = []

    if "llm_importance_level" not in existing_columns:
        statements.append(
            "ALTER TABLE comment ADD COLUMN llm_importance_level VARCHAR(20)"
        )

    if "llm_importance_score" not in existing_columns:
        statements.append("ALTER TABLE comment ADD COLUMN llm_importance_score FLOAT")

    if "llm_risk_level" not in existing_columns:
        statements.append("ALTER TABLE comment ADD COLUMN llm_risk_level VARCHAR(20)")

    return statements


def _build_uploaded_file_migrations(existing_columns: Set[str]) -> List[str]:
    """Build ALTER TABLE statements for uploaded_file table."""
    statements: List[str] = []

    if "original_filename" not in existing_columns:
        statements.append(
            "ALTER TABLE uploaded_file ADD COLUMN original_filename VARCHAR(255)"
        )

    if "content_type" not in existing_columns:
        statements.append(
            "ALTER TABLE uploaded_file ADD COLUMN content_type VARCHAR(100)"
        )

    if "total_rows" not in existing_columns:
        statements.append("ALTER TABLE uploaded_file ADD COLUMN total_rows INTEGER")

    if "processed_rows" not in existing_columns:
        statements.append("ALTER TABLE uploaded_file ADD COLUMN processed_rows INTEGER")

    return statements
