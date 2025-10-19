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

    if "comment" not in table_names:
        logger.info("Table 'comment' not found; skipping LLM column migration.")
        return

    existing_columns: Set[str] = {
        column["name"] for column in inspector.get_columns("comment")
    }

    statements = _build_comment_migrations(existing_columns)
    if not statements:
        logger.debug("LLM columns already present on 'comment' table; no migration run.")
        return

    with engine.begin() as connection:
        for statement in statements:
            logger.info("Applying migration: %s", statement)
            connection.execute(text(statement))

    logger.info("Applied %d migration statements on 'comment' table.", len(statements))


def _build_comment_migrations(existing_columns: Set[str]) -> List[str]:
    """Build ALTER TABLE statements for missing columns."""
    statements: List[str] = []

    if "llm_importance_level" not in existing_columns:
        statements.append("ALTER TABLE comment ADD COLUMN llm_importance_level VARCHAR(20)")

    if "llm_importance_score" not in existing_columns:
        statements.append("ALTER TABLE comment ADD COLUMN llm_importance_score FLOAT")

    if "llm_risk_level" not in existing_columns:
        statements.append("ALTER TABLE comment ADD COLUMN llm_risk_level VARCHAR(20)")

    return statements
