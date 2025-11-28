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

    # 主要テーブルを複数形へリネーム
    if "lecture" in table_names and "lectures" not in table_names:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE lecture RENAME TO lectures"))
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

    if "survey_response" in table_names and "survey_responses" not in table_names:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE survey_response RENAME TO survey_responses"))
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

    if "response_comment" in table_names and "response_comments" not in table_names:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE response_comment RENAME TO response_comments"))
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

    if "survey_summary" in table_names and "survey_summaries" not in table_names:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE survey_summary RENAME TO survey_summaries"))
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

    if "comment_summary" in table_names and "comment_summaries" not in table_names:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE comment_summary RENAME TO comment_summaries"))
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

    # survey_batch -> survey_batches リネーム、テーブルが無ければ作成
    if "survey_batch" in table_names and "survey_batches" not in table_names:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE survey_batch RENAME TO survey_batches"))
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

    if "survey_batches" not in table_names:
        _create_survey_batches_table(engine)
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
    else:
        survey_batch_columns: Set[str] = {
            column["name"] for column in inspector.get_columns("survey_batches")
        }
        _apply_statements(
            engine,
            _build_survey_batch_migrations(survey_batch_columns),
            table="survey_batches",
        )
        inspector = inspect(engine)
        survey_batch_columns = {
            column["name"] for column in inspector.get_columns("survey_batches")
        }
        if "upload_timestamp" in survey_batch_columns and engine.dialect.name == "sqlite":
            _rebuild_survey_batches_without_upload_timestamp(engine)

    # SurveyResponseテーブルのマイグレーションを適用
    if "survey_responses" in table_names:
        survey_response_columns: Set[str] = {
            column["name"] for column in inspector.get_columns("survey_responses")
        }
        _apply_statements(
            engine,
            _build_survey_response_migrations(survey_response_columns),
            table="survey_responses",
        )

    # Commentテーブルのマイグレーションを適用し新名称をresponse_commentとする
    if "response_comments" in table_names:
        comment_columns: Set[str] = {
            column["name"] for column in inspector.get_columns("response_comments")
        }
        _apply_statements(
            engine,
            _build_response_comment_migrations(comment_columns),
            table="response_comments",
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
            column["name"] for column in inspector.get_columns("response_comments")
        }
        _apply_statements(
            engine,
            _build_response_comment_migrations(comment_columns),
            table="response_comments",
        )
    else:
        logger.info("Table 'comment' not found; skipping comment migrations.")

    if "student" in table_names:
        _drop_student_table(engine)
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

    # uploaded_file -> uploaded_files リネーム
    if "uploaded_file" in table_names and "uploaded_files" not in table_names:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE uploaded_file RENAME TO uploaded_files"))
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

    if "uploaded_files" in table_names:
        uploaded_columns: Set[str] = {
            column["name"] for column in inspector.get_columns("uploaded_files")
        }
        _apply_statements(
            engine,
            _build_uploaded_file_migrations(uploaded_columns),
            table="uploaded_files",
        )
        inspector = inspect(engine)
        uploaded_columns = {column["name"] for column in inspector.get_columns("uploaded_files")}
        if "upload_timestamp" in uploaded_columns and engine.dialect.name == "sqlite":
            _rebuild_uploaded_files_without_upload_timestamp(engine)
    # lecture_metricsテーブルが無ければ作成
    if "lecture_metrics" not in table_names:
        _create_lecture_metrics_table(engine)

    # lecturesテーブルが無ければ作成、あれば不足カラムを追加
    if "lectures" not in table_names:
        _create_lecture_table(engine)
    else:
        lecture_columns: Set[str] = {
            column["name"] for column in inspector.get_columns("lectures")
        }
        _apply_statements(
            engine,
            _build_lecture_migrations(lecture_columns),
            table="lectures",
        )

    # サマリ系テーブルが無ければ作成
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "survey_summaries" not in table_names:
        _create_survey_summary_table(engine)
    else:
        survey_summary_columns: Set[str] = {
            column["name"] for column in inspector.get_columns("survey_summaries")
        }
        if "created_at" not in survey_summary_columns or "student_attribute" not in survey_summary_columns:
            _recreate_survey_summary_table(engine)
            inspector = inspect(engine)
            survey_summary_columns = {
                column["name"] for column in inspector.get_columns("survey_summaries")
            }
        _apply_statements(
            engine,
            _build_survey_summary_migrations(survey_summary_columns),
            table="survey_summaries",
        )

    if "comment_summaries" not in table_names:
        _create_comment_summary_table(engine)
    else:
        comment_summary_columns: Set[str] = {
            column["name"] for column in inspector.get_columns("comment_summaries")
        }
        legacy_cols = {
            "sentiment_positive",
            "category_lecture_content",
            "importance_low",
            "comments_count",
        }
        if legacy_cols & comment_summary_columns or "analysis_type" not in comment_summary_columns:
            _recreate_comment_summary_table(engine)
            inspector = inspect(engine)
            comment_summary_columns = {
                column["name"] for column in inspector.get_columns("comment_summaries")
            }
        _apply_statements(
            engine,
            _build_comment_summary_migrations(comment_summary_columns),
            table="comment_summaries",
        )

    if "score_distributions" not in table_names:
        _create_score_distribution_table(engine)
    else:
        dist_columns: Set[str] = {
            column["name"] for column in inspector.get_columns("score_distributions")
        }
        if "question_key" not in dist_columns and "metric_key" in dist_columns:
            _apply_statements(
                engine,
                ["ALTER TABLE score_distributions RENAME COLUMN metric_key TO question_key"],
                table="score_distributions",
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


def _rebuild_uploaded_files_without_upload_timestamp(engine: Engine) -> None:
    """SQLiteではDROP COLUMN未サポートの環境向けにuploaded_filesを再作成する。"""
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        connection.execute(text("ALTER TABLE uploaded_files RENAME TO uploaded_files__old"))
        connection.execute(
            text(
                """
            CREATE TABLE uploaded_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_name VARCHAR(255) NOT NULL,
                lecture_date DATE NOT NULL,
                lecture_number INTEGER NOT NULL,
                academic_year VARCHAR(10),
                period VARCHAR(100),
                status VARCHAR(20) NOT NULL,
                s3_key VARCHAR(512),
                uploaded_at TIMESTAMP NOT NULL,
                original_filename VARCHAR(255),
                content_type VARCHAR(100),
                total_rows INTEGER,
                processed_rows INTEGER,
                task_id VARCHAR(255),
                lecture_id INTEGER REFERENCES lectures(id),
                processing_started_at TIMESTAMP,
                processing_completed_at TIMESTAMP,
                error_message TEXT,
                finalized_at TIMESTAMP,
                CONSTRAINT uq_course_lecture_instance UNIQUE (course_name, lecture_date, lecture_number)
            )
            """
            )
        )
        connection.execute(
            text(
                """
            INSERT INTO uploaded_files (
                id, course_name, lecture_date, lecture_number, academic_year, period,
                status, s3_key, uploaded_at, original_filename, content_type,
                total_rows, processed_rows, task_id, lecture_id,
                processing_started_at, processing_completed_at, error_message, finalized_at
            )
            SELECT
                id, course_name, lecture_date, lecture_number, academic_year, period,
                status, s3_key, uploaded_at, original_filename, content_type,
                total_rows, processed_rows, task_id, lecture_id,
                processing_started_at, processing_completed_at, error_message, finalized_at
            FROM uploaded_files__old
            """
            )
        )
        connection.execute(text("DROP TABLE uploaded_files__old"))
        connection.execute(text("PRAGMA foreign_keys=ON"))


def _rebuild_survey_batches_without_upload_timestamp(engine: Engine) -> None:
    """SQLite向けにsurvey_batchesのupload_timestampを除去して再作成する。"""
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        connection.execute(text("ALTER TABLE survey_batches RENAME TO survey_batches__old"))
        connection.execute(
            text(
                """
            CREATE TABLE survey_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uploaded_file_id INTEGER NOT NULL UNIQUE REFERENCES uploaded_files(id),
                lecture_id INTEGER REFERENCES lectures(id),
                course_name VARCHAR(255) NOT NULL,
                lecture_date DATE NOT NULL,
                lecture_number INTEGER NOT NULL,
                academic_year VARCHAR(10),
                period VARCHAR(100),
                batch_type VARCHAR(20) DEFAULT 'preliminary' NOT NULL,
                zoom_participants INTEGER,
                recording_views INTEGER,
                status VARCHAR(20) NOT NULL,
                uploaded_at TIMESTAMP NOT NULL,
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
        connection.execute(
            text(
                """
            INSERT INTO survey_batches (
                id, uploaded_file_id, lecture_id, course_name, lecture_date, lecture_number,
                academic_year, period, status, uploaded_at, processing_started_at,
                processing_completed_at, finalized_at, error_message, total_responses, total_comments
            )
            SELECT
                id, uploaded_file_id, lecture_id, course_name, lecture_date, lecture_number,
                academic_year, period, status, uploaded_at, processing_started_at,
                processing_completed_at, finalized_at, error_message, total_responses, total_comments
            FROM survey_batches__old
            """
            )
        )
        connection.execute(text("DROP TABLE survey_batches__old"))
        connection.execute(text("PRAGMA foreign_keys=ON"))


def _build_comment_migrations(existing_columns: Set[str]) -> List[str]:
    """不足カラム向けのALTER TABLE文を生成する。"""
    statements: List[str] = []

    if "account_id" not in existing_columns:
        statements.append("ALTER TABLE comment ADD COLUMN account_id VARCHAR(255)")

    if "account_name" not in existing_columns:
        statements.append("ALTER TABLE comment ADD COLUMN account_name VARCHAR(255)")

    if "question_text" not in existing_columns:
        statements.append("ALTER TABLE comment ADD COLUMN question_text TEXT")

    if "response_id" not in existing_columns:
        statements.append(
            "ALTER TABLE comment ADD COLUMN response_id INTEGER REFERENCES survey_responses(id)"
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

    if "file_id" in existing_columns and "uploaded_file_id" not in existing_columns:
        statements.append(
            "ALTER TABLE survey_responses RENAME COLUMN file_id TO uploaded_file_id"
        )

    if "survey_batch_id" not in existing_columns:
        statements.append(
            "ALTER TABLE survey_responses ADD COLUMN survey_batch_id INTEGER REFERENCES survey_batches(id)"
        )

    if "row_index" not in existing_columns:
        statements.append("ALTER TABLE survey_responses ADD COLUMN row_index INTEGER")

    if "student_attribute" not in existing_columns:
        statements.append("ALTER TABLE survey_responses ADD COLUMN student_attribute VARCHAR(50) NOT NULL")
    else:
        statements.append("ALTER TABLE survey_responses ALTER COLUMN student_attribute SET NOT NULL")

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
        "score_instructor_time": "INTEGER",
        "score_instructor_qa": "INTEGER",
        "score_instructor_speaking": "INTEGER",
        "score_self_future": "INTEGER",
        "score_recommend_friend": "INTEGER",
    }

    for col, col_type in new_score_columns.items():
        if col not in existing_columns:
            statements.append(
                f"ALTER TABLE survey_responses ADD COLUMN {col} {col_type}"
            )
    if "score_recommend_to_friend" in existing_columns:
        statements.append("ALTER TABLE survey_responses DROP COLUMN score_recommend_to_friend")

    return statements


def _build_survey_batch_migrations(existing_columns: Set[str]) -> List[str]:
    statements: List[str] = []
    if "file_id" in existing_columns and "uploaded_file_id" not in existing_columns:
        statements.append("ALTER TABLE survey_batches RENAME COLUMN file_id TO uploaded_file_id")
    if "uploaded_at" not in existing_columns and "upload_timestamp" in existing_columns:
        statements.append("ALTER TABLE survey_batches ADD COLUMN uploaded_at TIMESTAMP")
        statements.append(
            "UPDATE survey_batches SET uploaded_at = upload_timestamp WHERE uploaded_at IS NULL"
        )
    if "upload_timestamp" in existing_columns:
        statements.append("ALTER TABLE survey_batches DROP COLUMN upload_timestamp")
    if "status" not in existing_columns and "processing_status" in existing_columns:
        statements.append(
            "ALTER TABLE survey_batches RENAME COLUMN processing_status TO status"
        )
    if "batch_type" not in existing_columns:
        statements.append("ALTER TABLE survey_batches ADD COLUMN batch_type VARCHAR(20) DEFAULT 'preliminary'")
    if "zoom_participants" not in existing_columns:
        statements.append("ALTER TABLE survey_batches ADD COLUMN zoom_participants INTEGER")
    if "recording_views" not in existing_columns:
        statements.append("ALTER TABLE survey_batches ADD COLUMN recording_views INTEGER")
    return statements


def _build_response_comment_migrations(existing_columns: Set[str]) -> List[str]:
    statements: List[str] = []

    # 旧commentテーブル由来のカラムが改名後に不足している可能性を考慮する
    if "account_id" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comments ADD COLUMN account_id VARCHAR(255)"
        )
    if "account_name" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comments ADD COLUMN account_name VARCHAR(255)"
        )
    if "question_type" not in existing_columns:
        statements.append("ALTER TABLE response_comments ADD COLUMN question_type VARCHAR(50) NOT NULL")
    else:
        statements.append("ALTER TABLE response_comments ALTER COLUMN question_type SET NOT NULL")
    if "file_id" in existing_columns and "uploaded_file_id" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comments RENAME COLUMN file_id TO uploaded_file_id"
        )
    if "question_text" not in existing_columns:
        statements.append("ALTER TABLE response_comments ADD COLUMN question_text TEXT")
    if "response_id" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comments ADD COLUMN response_id INTEGER REFERENCES survey_responses(id)"
        )
    if "comment_text" not in existing_columns:
        statements.append("ALTER TABLE response_comments ADD COLUMN comment_text TEXT")
    if "llm_importance_level" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comments ADD COLUMN llm_importance_level VARCHAR(20)"
        )
    if "llm_importance_score" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comments ADD COLUMN llm_importance_score FLOAT"
        )
    if "llm_risk_level" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comments ADD COLUMN llm_risk_level VARCHAR(20)"
        )
    if "llm_is_abusive" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comments ADD COLUMN llm_is_abusive BOOLEAN"
        )
    if "is_analyzed" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comments ADD COLUMN is_analyzed BOOLEAN"
        )
    if "analysis_version" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comments ADD COLUMN analysis_version VARCHAR(20)"
        )

    if "survey_batch_id" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comments ADD COLUMN survey_batch_id INTEGER REFERENCES survey_batches(id)"
        )
    if "is_important" not in existing_columns:
        statements.append(
            "ALTER TABLE response_comments ADD COLUMN is_important INTEGER"
        )

    return statements


def _build_uploaded_file_migrations(existing_columns: Set[str]) -> List[str]:
    """uploaded_files向けALTER TABLE文を生成する。"""
    statements: List[str] = []

    if "id" not in existing_columns and "file_id" in existing_columns:
        statements.append("ALTER TABLE uploaded_files RENAME COLUMN file_id TO id")

    if "status" not in existing_columns and "processing_status" in existing_columns:
        statements.append(
            "ALTER TABLE uploaded_files RENAME COLUMN processing_status TO status"
        )

    if "uploaded_at" not in existing_columns:
        statements.append("ALTER TABLE uploaded_files ADD COLUMN uploaded_at TIMESTAMP")
        if "upload_timestamp" in existing_columns:
            statements.append(
                "UPDATE uploaded_files SET uploaded_at = upload_timestamp WHERE uploaded_at IS NULL"
            )
    if "upload_timestamp" in existing_columns:
        statements.append("ALTER TABLE uploaded_files DROP COLUMN upload_timestamp")

    if "original_filename" not in existing_columns:
        statements.append(
            "ALTER TABLE uploaded_files ADD COLUMN original_filename VARCHAR(255)"
        )

    if "content_type" not in existing_columns:
        statements.append(
            "ALTER TABLE uploaded_files ADD COLUMN content_type VARCHAR(100)"
        )

    if "total_rows" not in existing_columns:
        statements.append("ALTER TABLE uploaded_files ADD COLUMN total_rows INTEGER")

    if "processed_rows" not in existing_columns:
        statements.append("ALTER TABLE uploaded_files ADD COLUMN processed_rows INTEGER")

    if "finalized_at" not in existing_columns:
        statements.append("ALTER TABLE uploaded_files ADD COLUMN finalized_at TIMESTAMP")

    if "lecture_id" not in existing_columns:
        statements.append(
            "ALTER TABLE uploaded_files ADD COLUMN lecture_id INTEGER REFERENCES lectures(id)"
        )

    if "academic_year" not in existing_columns:
        statements.append(
            "ALTER TABLE uploaded_files ADD COLUMN academic_year VARCHAR(10)"
        )

    if "period" not in existing_columns:
        statements.append("ALTER TABLE uploaded_files ADD COLUMN period VARCHAR(100)")

    return statements


def _build_comment_summary_migrations(existing_columns: Set[str]) -> List[str]:
    statements: List[str] = []
    if "student_attribute" not in existing_columns:
        statements.append(
            "ALTER TABLE comment_summaries ADD COLUMN student_attribute VARCHAR(50) DEFAULT 'ALL'"
        )
    if "analysis_type" not in existing_columns:
        statements.append(
            "ALTER TABLE comment_summaries ADD COLUMN analysis_type VARCHAR(20)"
        )
    if "label" not in existing_columns:
        statements.append("ALTER TABLE comment_summaries ADD COLUMN label VARCHAR(50)")
    if "count" not in existing_columns:
        statements.append("ALTER TABLE comment_summaries ADD COLUMN count INTEGER")
    if "created_at" not in existing_columns:
        statements.append(
            "ALTER TABLE comment_summaries ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        )
    return statements


def _build_survey_summary_migrations(existing_columns: Set[str]) -> List[str]:
    statements: List[str] = []
    if "created_at" not in existing_columns:
        statements.append(
            "ALTER TABLE survey_summaries ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        )
    return statements


def _build_lecture_migrations(existing_columns: Set[str]) -> List[str]:
    statements: List[str] = []
    if "term" not in existing_columns:
        statements.append("ALTER TABLE lectures ADD COLUMN term VARCHAR(50)")
        statements.append("UPDATE lectures SET term = period WHERE term IS NULL")
    if "name" not in existing_columns:
        statements.append("ALTER TABLE lectures ADD COLUMN name VARCHAR(255)")
        statements.append("UPDATE lectures SET name = course_name WHERE name IS NULL")
    if "session" not in existing_columns:
        statements.append("ALTER TABLE lectures ADD COLUMN session VARCHAR(50)")
    if "lecture_date" not in existing_columns:
        statements.append("ALTER TABLE lectures ADD COLUMN lecture_date DATE")
    if "instructor_name" not in existing_columns:
        statements.append("ALTER TABLE lectures ADD COLUMN instructor_name VARCHAR(255)")
    if "description" not in existing_columns:
        statements.append("ALTER TABLE lectures ADD COLUMN description TEXT")
    if "created_at" not in existing_columns:
        statements.append(
            "ALTER TABLE lectures ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        )
    if "updated_at" not in existing_columns:
        statements.append(
            "ALTER TABLE lectures ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
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
        Column("file_id", Integer, ForeignKey("uploaded_files.id"), nullable=False),
        Column("score_satisfaction_overall", Integer),
        Column("comment_text", Text, nullable=False),
        Column("llm_category", String(50)),
        Column("llm_sentiment", String(20)),
        Column("llm_summary", Text),
        Column("llm_importance_level", String(20)),
        Column("llm_importance_score", Float),
        Column("llm_risk_level", String(20)),
        Column("llm_is_abusive", String(5)),
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
        _safe_column(old_comment, "llm_is_abusive", existing_columns),
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
                    "llm_is_abusive",
                    "processed_at",
                    "analysis_version",
                ],
                select_stmt,
            )
        )
        connection.execute(text("DROP TABLE comment"))
        connection.execute(text("ALTER TABLE comment__new RENAME TO response_comments"))


def _safe_column(table: Table, column_name: str, existing_columns: Set[str]):
    if column_name in existing_columns:
        return table.c[column_name]
    return literal(None).label(column_name)


def _drop_student_table(engine: Engine) -> None:
    logger.info("Dropping legacy 'student' table.")
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS student"))


def _recreate_comment_summary_table(engine: Engine) -> None:
    """Legacy wide comment_summaryを新スキーマへ再作成する。"""
    with engine.begin() as connection:
        logger.info("Recreating legacy 'comment_summary' table to tall format.")
        connection.execute(text("DROP TABLE IF EXISTS comment_summaries"))
    _create_comment_summary_table(engine)


def _recreate_survey_summary_table(engine: Engine) -> None:
    with engine.begin() as connection:
        logger.info("Recreating legacy 'survey_summary' table to match schema.")
        connection.execute(text("DROP TABLE IF EXISTS survey_summaries"))
    _create_survey_summary_table(engine)


def _create_lecture_metrics_table(engine: Engine) -> None:
    with engine.begin() as connection:
        logger.info("Creating table 'lecture_metrics'.")
        connection.execute(
            text(
                """
            CREATE TABLE lecture_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uploaded_file_id INTEGER NOT NULL UNIQUE REFERENCES uploaded_files(id),
                zoom_participants INTEGER,
                recording_views INTEGER,
                updated_at TIMESTAMP
            )
            """
            )
        )


def _create_lecture_table(engine: Engine) -> None:
    with engine.begin() as connection:
        logger.info("Creating table 'lectures'.")
        connection.execute(
            text(
                """
            CREATE TABLE lectures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_name VARCHAR(255) NOT NULL,
                academic_year INTEGER,
                period VARCHAR(100) NOT NULL,
                term VARCHAR(50),
                name VARCHAR(255),
                session VARCHAR(50),
                lecture_date DATE,
                instructor_name VARCHAR(255),
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                category VARCHAR(20),
                CONSTRAINT uq_lecture_identity UNIQUE (name, academic_year, term, session, lecture_date)
            )
            """
            )
        )


def _rename_comment_table(engine: Engine) -> None:
    with engine.begin() as connection:
        logger.info("Renaming table 'comment' to 'response_comments'.")
        connection.execute(text("ALTER TABLE comment RENAME TO response_comments"))


def _create_survey_batches_table(engine: Engine) -> None:
    with engine.begin() as connection:
        logger.info("Creating table 'survey_batches'.")
        connection.execute(
            text(
                """
            CREATE TABLE survey_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uploaded_file_id INTEGER NOT NULL UNIQUE REFERENCES uploaded_files(id),
                lecture_id INTEGER REFERENCES lecture(id),
                course_name VARCHAR(255) NOT NULL,
                lecture_date DATE NOT NULL,
                lecture_number INTEGER NOT NULL,
                academic_year VARCHAR(10),
                period VARCHAR(100),
                status VARCHAR(20) NOT NULL,
                uploaded_at TIMESTAMP NOT NULL,
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
            CREATE TABLE survey_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                survey_batch_id INTEGER NOT NULL REFERENCES survey_batches(id),
                analysis_version VARCHAR(20) NOT NULL DEFAULT 'preliminary',
                student_attribute VARCHAR(50),
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
                response_count INTEGER,
                comments_count INTEGER,
                important_comments_count INTEGER,
                updated_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_survey_summary_batch_version UNIQUE (survey_batch_id, analysis_version, student_attribute)
            )
            """
            )
        )


def _create_comment_summary_table(engine: Engine) -> None:
    with engine.begin() as connection:
        logger.info("Creating table 'comment_summaries'.")
        connection.execute(
            text(
                """
            CREATE TABLE comment_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                survey_batch_id INTEGER NOT NULL REFERENCES survey_batches(id),
                analysis_version VARCHAR(20) NOT NULL DEFAULT 'preliminary',
                student_attribute VARCHAR(50) NOT NULL DEFAULT 'ALL',
                analysis_type VARCHAR(20) NOT NULL,
                label VARCHAR(50) NOT NULL,
                count INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_comment_summary_entry UNIQUE (survey_batch_id, analysis_version, student_attribute, analysis_type, label)
            )
            """
            )
        )


def _create_score_distribution_table(engine: Engine) -> None:
    with engine.begin() as connection:
        logger.info("Creating table 'score_distributions'.")
        connection.execute(
            text(
                """
            CREATE TABLE score_distributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                survey_batch_id INTEGER NOT NULL REFERENCES survey_batches(id),
                student_attribute VARCHAR(50) NOT NULL,
                question_key VARCHAR(50) NOT NULL,
                score_value INTEGER NOT NULL,
                count INTEGER NOT NULL,
                CONSTRAINT uq_score_distribution_entry UNIQUE (survey_batch_id, student_attribute, question_key, score_value)
            )
            """
            )
        )
