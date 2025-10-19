from sqlalchemy import Column, Integer, MetaData, Table, Text, create_engine, inspect

from app.db.migrations import apply_migrations


def test_apply_migrations_adds_missing_columns() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    Table(
        "comment",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("comment_learned_raw", Text),
    )
    metadata.create_all(engine)

    apply_migrations(engine)

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("comment")}

    assert {"llm_importance_level", "llm_importance_score", "llm_risk_level"} <= columns


def test_apply_migrations_is_idempotent() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    Table(
        "comment",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("comment_learned_raw", Text),
        Column("llm_importance_level", Text),
        Column("llm_importance_score", Integer),
        Column("llm_risk_level", Text),
    )
    metadata.create_all(engine)

    apply_migrations(engine)

    inspector = inspect(engine)
    columns = [column["name"] for column in inspector.get_columns("comment")]
    assert columns.count("llm_importance_level") == 1
    assert columns.count("llm_importance_score") == 1
    assert columns.count("llm_risk_level") == 1
