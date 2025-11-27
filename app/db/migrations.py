from __future__ import annotations

import logging
from typing import List, Sequence, Set

from sqlalchemy import (
    TIMESTAMP,
    Column,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    func,
    inspect,
    literal,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.schema import Table

logger = logging.getLogger(__name__)


def apply_migrations(engine: Engine) -> None:
    """既存データベースで必要なカラムを欠けなく維持する。"""
    if engine is None:
        logger.warning("No database engine provided; skipping migrations.")
        return

    inspector = inspect(engine)
    table_names: Sequence[str] = inspector.get_table_names()

    # survey_batch テーブルが必要なため先に作成
    if "survey_batch" not in table_names:
        _create_survey_batch_table(engine)
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

    # SurveyResponseテーブルのマイグレーションを適用
    if "survey_response" in table_names:
        survey_response_columns: Set[str] = {
            column["name"] for column in inspector.get_columns("survey_response")
        }
        _apply_statements(
            engine,
            _build_survey_response_migrations(survey_response_columns),
            table="survey_response",
        )

    # Commentテーブルのマイグレーションを適用し新名称をresponse_commentとする
    if "response_comment" in table_names:
        comment_columns: Set[str] = {
            column["name"] for column in inspector.get_columns("response_comment")
        }
        _apply_statements(
            engine,
            _build_response_comment_migrations(comment_columns),
            table="response_comment",
        )
    elif "comment" in table_names:
        comment_columns: Set[str] = {
            column["name"] for column in inspector.get_columns("comment")
        }
        if _requires_comment_rebuild(comment_columns):
            _rebuild_comment_table(engine, comment_columns)
            inspector = inspect(engine)
            comment_columns = {
                column["name"] for column in inspector.get_columns("comment")
            }
        _rename_comment_table(engine)
        inspector = inspect(engine)
        comment_columns = {
            column["name"] for column in inspector.get_columns("response_comment")
        }
        _apply_statements(
            engine,
            _build_response_comment_migrations(comment_columns),
            table="response_comment",
        )
    else:
        logger.info("Table 'comment' not found; skipping comment migrations.")

    if "student" in table_names:
        _drop_student_table(engine)
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

    if "uploaded_file" in table_names:
        uploaded_columns: Set[str] = {
            column["name"] for column in inspector.get_columns("uploaded_file")
        }
        _apply_statements(
            engine,
            _build_uploaded_file_migrations(uploaded_columns),
            table="uploaded_file",
        )
    # lecture_metricsテーブルが無ければ作成
    if "lecture_metrics" not in table_names:
        _create_lecture_metrics_table(engine)

    # lectureテーブルが無ければ作成
    if "lecture" not in table_names:
        _create_lecture_table(engine)

    else:
        logger.info(
            "Table 'uploaded_file' not found; skipping storage column migration."
        )

    # サマリ系テーブルが無ければ作成
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "survey_summary" not in table_names:
        _create_survey_summary_table(engine)
    else:
        survey_summary_columns: Set[str] = {
            column["name"] for column in inspector.get_columns("survey_summary")
        }
        # 既存テーブルに対するカラム追加が必要な場合はここに追加

    if "comment_summary" not in table_names:
        _create_comment_summary_table(engine)
    else:
        comment_summary_columns: Set[str] = {
            column["name"] for column in inspector.get_columns("comment_summary")
        }
        _apply_statements(
            engine,
            _build_comment_summary_migrations(comment_summary_columns),
            table="comment_summary",
        )


def _apply_statements(engine: Engine, statements: List[str], *, table: str) -> None:
    if not statements:
        logger.debug("No schema migrations required for table '%s'.", table)
        return

    with engine.begin() as connection:
        for statement in statements:
            logger.info("Applying migration: %s", statement)
            connection.execute(text(statement))

    logger.info(
        "Applied %d migration statements for table '%s'.", len(statements), table
    )


def _build_comment_migrations(existing_columns: Set[str]) -> List[str]:
    """不足カラム向けのALTER TABLE文を生成する。"""
    statements: List[str] = []

    if "account_id" not in existing_columns:
        statements.append("ALTER TABLE comment ADD COLUMN account_id VARCHAR(255)")

    if "account_name" not in existing_columns:
        statements.append("ALTER TABLE comment ADD COLUMN account_name VARCHAR(255)")

    if "question_text" not in existing_columns:
        statements.append("ALTER TABLE comment ADD COLUMN question_text TEXT")

    if "survey_response_id" not in existing_columns:
        statements.append(
            "ALTER TABLE comment ADD COLUMN survey_response_id INTEGER REFERENCES survey_response(id)"
        )

    if "comment_text" not in existing_columns:
        statements.append("ALTER TABLE comment ADD COLUMN comment_text TEXT")

    if "llm_importance_level" not in existing_columns:
        statements.append(
            "ALTER TABLE comment ADD COLUMN llm_importance_level VARCHAR(20)"
        )

    if "llm_importance_score" not in existing_columns:
        statements.append("ALTER TABLE comment ADD COLUMN llm_importance_score FLOAT")

    if "llm_risk_level" not in existing_columns:
        statements.append("ALTER TABLE comment ADD COLUMN llm_risk_level VARCHAR(20)")

    if "analysis_version" not in existing_columns:
        statements.append("ALTER TABLE comment ADD COLUMN analysis_version VARCHAR(20)")

    return statements


def _build_survey_response_migrations(existing_columns: Set[str]) -> List[str]:
    """survey_response向けALTER TABLE文を生成する。"""
    statements: List[str] = []

    if "survey_batch_id" not in existing_columns:
        statements.append(
            "ALTER TABLE survey_response ADD COLUMN survey_batch_id INTEGER REFERENCES survey_batch(id)"
        )

    if "row_index" not in existing_columns:
        statements.append("ALTER TABLE survey_response ADD COLUMN row_index INTEGER")

    # 本番用CSVの全数値評価カラムを追加
    new_score_columns = {
        "score_satisfaction_content_volume": "INTEGER",
        "score_satisfaction_content_understanding": "INTEGER",
        "score_satisfaction_content_announcement": "INTEGER",
        "score_satisfaction_instructor_overall": "INTEGER",
        "score_satisfaction_instructor_efficiency": "INTEGER",
        "score_satisfaction_instructor_response": "INTEGER",
        "score_satisfaction_instructor_clarity": "INTEGER",
        "score_self_preparation": "INTEGER",
        "score_self_motivation": "INTEGER",
        "score_self_applicability": "INTEGER",
        "score_recommend_to_friend": "INTEGER",
    }

    for col, col_type in new_score_columns.items():
        if col not in existing_columns:
            statements.append(
                f"ALTER TABLE survey_response ADD COLUMN {col} {col_type}"
            )

    return statements


def _build_response_comment_migrations(existing_columns: Set[str]) -> List[str]:
    statements: List[str] = []

    # 旧commentテーブル由来のカラムが改名後に不足している可能性を考慮する
    if "account_id" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comment ADD COLUMN account_id VARCHAR(255)"
        )
    if "account_name" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comment ADD COLUMN account_name VARCHAR(255)"
        )
    if "question_text" not in existing_columns:
        statements.append("ALTER TABLE response_comment ADD COLUMN question_text TEXT")
    if "survey_response_id" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comment ADD COLUMN survey_response_id INTEGER REFERENCES survey_response(id)"
        )
    if "comment_text" not in existing_columns:
        statements.append("ALTER TABLE response_comment ADD COLUMN comment_text TEXT")
    if "llm_importance_level" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comment ADD COLUMN llm_importance_level VARCHAR(20)"
        )
    if "llm_importance_score" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comment ADD COLUMN llm_importance_score FLOAT"
        )
    if "llm_risk_level" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comment ADD COLUMN llm_risk_level VARCHAR(20)"
        )
    if "analysis_version" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comment ADD COLUMN analysis_version VARCHAR(20)"
        )

    if "survey_batch_id" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comment ADD COLUMN survey_batch_id INTEGER REFERENCES survey_batch(id)"
        )
    if "is_important" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comment ADD COLUMN is_important INTEGER"
        )

    return statements


def _build_uploaded_file_migrations(existing_columns: Set[str]) -> List[str]:
    """uploaded_file向けALTER TABLE文を生成する。"""
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

    if "finalized_at" not in existing_columns:
        statements.append("ALTER TABLE uploaded_file ADD COLUMN finalized_at TIMESTAMP")

    if "lecture_id" not in existing_columns:
        statements.append(
            "ALTER TABLE uploaded_file ADD COLUMN lecture_id INTEGER REFERENCES lecture(id)"
        )

    if "academic_year" not in existing_columns:
        statements.append(
            "ALTER TABLE uploaded_file ADD COLUMN academic_year VARCHAR(10)"
        )

    if "period" not in existing_columns:
        statements.append("ALTER TABLE uploaded_file ADD COLUMN period VARCHAR(100)")

    return statements


def _build_comment_summary_migrations(existing_columns: Set[str]) -> List[str]:
    statements: List[str] = []
    if "comments_count" not in existing_columns:
        statements.append(
            "ALTER TABLE comment_summary ADD COLUMN comments_count INTEGER"
        )
    return statements


def _requires_comment_rebuild(existing_columns: Set[str]) -> bool:
    legacy_columns = {"student_id", "comment_learned_raw", "comment_improvements_raw"}
    if legacy_columns & existing_columns:
        return True
    if "comment_text" not in existing_columns:
        return True
    return False


def _rebuild_comment_table(engine: Engine, existing_columns: Set[str]) -> None:
    logger.info("Rebuilding legacy 'comment' table to new schema.")
    metadata = MetaData()
    old_comment = Table("comment", metadata, autoload_with=engine)

    temp_table = Table(
        "comment__new",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("file_id", Integer, ForeignKey("uploaded_file.file_id"), nullable=False),
        Column("score_satisfaction_overall", Integer),
        Column("comment_text", Text, nullable=False),
        Column("llm_category", String(50)),
        Column("llm_sentiment", String(20)),
        Column("llm_summary", Text),
        Column("llm_importance_level", String(20)),
        Column("llm_importance_score", Float),
        Column("llm_risk_level", String(20)),
        Column("processed_at", TIMESTAMP),
        Column("analysis_version", String(20)),
    )

    comment_text_source = None
    if "comment_text" in existing_columns:
        comment_text_source = old_comment.c["comment_text"]
    elif "comment_learned_raw" in existing_columns:
        comment_text_source = old_comment.c["comment_learned_raw"]

    select_stmt = select(
        old_comment.c["id"],
        old_comment.c["file_id"],
        _safe_column(old_comment, "score_satisfaction_overall", existing_columns),
        func.coalesce(
            comment_text_source if comment_text_source is not None else literal(""),
            literal(""),
        ).label("comment_text"),
        _safe_column(old_comment, "llm_category", existing_columns),
        _safe_column(old_comment, "llm_sentiment", existing_columns),
        _safe_column(old_comment, "llm_summary", existing_columns),
        _safe_column(old_comment, "llm_importance_level", existing_columns),
        _safe_column(old_comment, "llm_importance_score", existing_columns),
        _safe_column(old_comment, "llm_risk_level", existing_columns),
        _safe_column(old_comment, "processed_at", existing_columns),
    )

    with engine.begin() as connection:
        if engine.dialect.has_table(connection, "comment__new"):
            connection.execute(text("DROP TABLE comment__new"))

        temp_table.create(bind=connection)
        connection.execute(
            temp_table.insert().from_select(
                [
                    "id",
                    "file_id",
                    "score_satisfaction_overall",
                    "comment_text",
                    "llm_category",
                    "llm_sentiment",
                    "llm_summary",
                    "llm_importance_level",
                    "llm_importance_score",
                    "llm_risk_level",
                    "processed_at",
                    "analysis_version",
                ],
                select_stmt,
            )
        )
        connection.execute(text("DROP TABLE comment"))
        connection.execute(text("ALTER TABLE comment__new RENAME TO comment"))


def _safe_column(table: Table, column_name: str, existing_columns: Set[str]):
    if column_name in existing_columns:
        return table.c[column_name]
    return literal(None).label(column_name)


def _drop_student_table(engine: Engine) -> None:
    logger.info("Dropping legacy 'student' table.")
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS student"))


def _create_lecture_metrics_table(engine: Engine) -> None:
    with engine.begin() as connection:
        logger.info("Creating table 'lecture_metrics'.")
        connection.execute(
            text(
                """
            CREATE TABLE lecture_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL UNIQUE REFERENCES uploaded_file(file_id),
                zoom_participants INTEGER,
                recording_views INTEGER,
                updated_at TIMESTAMP
            )
            """
            )
        )


def _create_lecture_table(engine: Engine) -> None:
    with engine.begin() as connection:
        logger.info("Creating table 'lecture'.")
        connection.execute(
            text(
                """
            CREATE TABLE lecture (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_name VARCHAR(255) NOT NULL,
                academic_year INTEGER,
                period VARCHAR(100) NOT NULL,
                category VARCHAR(20),
                CONSTRAINT uq_lecture_identity UNIQUE (course_name, academic_year, period)
            )
            """
            )
        )


def _rename_comment_table(engine: Engine) -> None:
    with engine.begin() as connection:
        logger.info("Renaming table 'comment' to 'response_comment'.")
        connection.execute(text("ALTER TABLE comment RENAME TO response_comment"))


def _create_survey_batch_table(engine: Engine) -> None:
    with engine.begin() as connection:
        logger.info("Creating table 'survey_batch'.")
        connection.execute(
            text(
                """
            CREATE TABLE survey_batch (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL UNIQUE REFERENCES uploaded_file(file_id),
                lecture_id INTEGER REFERENCES lecture(id),
                course_name VARCHAR(255) NOT NULL,
                lecture_date DATE NOT NULL,
                lecture_number INTEGER NOT NULL,
                academic_year VARCHAR(10),
                period VARCHAR(100),
                status VARCHAR(20) NOT NULL,
                upload_timestamp TIMESTAMP NOT NULL,
                processing_started_at TIMESTAMP,
                processing_completed_at TIMESTAMP,
                finalized_at TIMESTAMP,
                error_message TEXT,
                total_responses INTEGER,
                total_comments INTEGER,
                CONSTRAINT uq_survey_batch_identity UNIQUE (course_name, lecture_date, lecture_number)
            )
            """
            )
        )


def _create_survey_summary_table(engine: Engine) -> None:
    with engine.begin() as connection:
        logger.info("Creating table 'survey_summary'.")
        connection.execute(
            text(
                """
            CREATE TABLE survey_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                survey_batch_id INTEGER NOT NULL REFERENCES survey_batch(id),
                analysis_version VARCHAR(20) NOT NULL DEFAULT 'preliminary',
                score_overall_satisfaction FLOAT,
                score_content_volume FLOAT,
                score_content_understanding FLOAT,
                score_content_announcement FLOAT,
                score_instructor_overall FLOAT,
                score_instructor_time FLOAT,
                score_instructor_qa FLOAT,
                score_instructor_speaking FLOAT,
                score_self_preparation FLOAT,
                score_self_motivation FLOAT,
                score_self_future FLOAT,
                nps_score FLOAT,
                nps_promoters INTEGER,
                nps_passives INTEGER,
                nps_detractors INTEGER,
                nps_total INTEGER,
                responses_count INTEGER,
                comments_count INTEGER,
                important_comments_count INTEGER,
                updated_at TIMESTAMP,
                CONSTRAINT uq_survey_summary_batch_version UNIQUE (survey_batch_id, analysis_version)
            )
            """
            )
        )


def _create_comment_summary_table(engine: Engine) -> None:
    with engine.begin() as connection:
        logger.info("Creating table 'comment_summary'.")
        connection.execute(
            text(
                """
            CREATE TABLE comment_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                survey_batch_id INTEGER NOT NULL REFERENCES survey_batch(id),
                analysis_version VARCHAR(20) NOT NULL DEFAULT 'preliminary',
                sentiment_positive INTEGER,
                sentiment_negative INTEGER,
                sentiment_neutral INTEGER,
                category_lecture_content INTEGER,
                category_lecture_material INTEGER,
                category_operations INTEGER,
                category_other INTEGER,
                importance_low INTEGER,
                importance_medium INTEGER,
                importance_high INTEGER,
                important_comments_count INTEGER,
                comments_count INTEGER,
                updated_at TIMESTAMP,
                CONSTRAINT uq_comment_summary_batch_version UNIQUE (survey_batch_id, analysis_version)
            )
            """
            )
        )
