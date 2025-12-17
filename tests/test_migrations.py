from sqlalchemy import Column, Integer, MetaData, Table, Text, create_engine, inspect

from app.db.migrations import apply_migrations


def _target_comment_table(inspector):
    table_names = inspector.get_table_names()
    if "response_comments" in table_names:
        return "response_comments"
    if "response_comment" in table_names:
        return "response_comment"
    return "comment"


def test_apply_migrations_adds_missing_columns() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    Table(
        "comment",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("comment_text", Text),
    )
    metadata.create_all(engine)

    apply_migrations(engine)

    inspector = inspect(engine)
    table_name = _target_comment_table(inspector)
    columns = {column["name"] for column in inspector.get_columns(table_name)}

    # llm_importance_level is renamed to llm_priority
    assert {
        "llm_priority",
        "llm_importance_score",
        "llm_risk_level",
        "llm_fix_difficulty",
    } <= columns


def test_apply_migrations_is_idempotent() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    Table(
        "comment",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("comment_text", Text),
        Column("llm_importance_level", Text),
        Column("llm_importance_score", Integer),
        Column("llm_risk_level", Text),
    )
    metadata.create_all(engine)

    apply_migrations(engine)

    inspector = inspect(engine)
    table_name = _target_comment_table(inspector)
    columns = [column["name"] for column in inspector.get_columns(table_name)]
    # Migration renames llm_importance_level to llm_priority
    assert columns.count("llm_importance_level") == 0
    assert columns.count("llm_priority") == 1
    assert columns.count("llm_fix_difficulty") == 1
    assert columns.count("llm_importance_score") == 1
    assert columns.count("llm_risk_level") == 1
