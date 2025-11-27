"""baseline current schema

Revision ID: 202410171200
Revises: 
Create Date: 2024-10-17 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "202410171200"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lecture",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("course_name", sa.String(length=255), nullable=False),
        sa.Column("academic_year", sa.Integer(), nullable=True),
        sa.Column("period", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "course_name",
            "academic_year",
            "period",
            name="uq_lecture_identity",
        ),
    )

    op.create_table(
        "uploaded_file",
        sa.Column("file_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("course_name", sa.String(length=255), nullable=False),
        sa.Column("lecture_date", sa.Date(), nullable=False),
        sa.Column("lecture_number", sa.Integer(), nullable=False),
        sa.Column("academic_year", sa.String(length=10), nullable=True),
        sa.Column("period", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("s3_key", sa.String(length=512), nullable=True),
        sa.Column("upload_timestamp", sa.TIMESTAMP(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("total_rows", sa.Integer(), nullable=True),
        sa.Column("processed_rows", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.String(length=255), nullable=True),
        sa.Column(
            "lecture_id", sa.Integer(), sa.ForeignKey("lecture.id"), nullable=True
        ),
        sa.Column("processing_started_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("processing_completed_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("finalized_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("file_id"),
        sa.UniqueConstraint(
            "course_name",
            "lecture_date",
            "lecture_number",
            name="uq_course_lecture_instance",
        ),
    )

    op.create_table(
        "survey_batch",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column(
            "lecture_id", sa.Integer(), sa.ForeignKey("lecture.id"), nullable=True
        ),
        sa.Column("course_name", sa.String(length=255), nullable=False),
        sa.Column("lecture_date", sa.Date(), nullable=False),
        sa.Column("lecture_number", sa.Integer(), nullable=False),
        sa.Column("academic_year", sa.String(length=10), nullable=True),
        sa.Column("period", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("upload_timestamp", sa.TIMESTAMP(), nullable=False),
        sa.Column("processing_started_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("processing_completed_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("finalized_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("total_responses", sa.Integer(), nullable=True),
        sa.Column("total_comments", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id"),
        sa.UniqueConstraint(
            "course_name",
            "lecture_date",
            "lecture_number",
            name="uq_survey_batch_identity",
        ),
        sa.ForeignKeyConstraint(["file_id"], ["uploaded_file.file_id"]),
    )

    op.create_table(
        "survey_response",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("survey_batch_id", sa.Integer(), nullable=True),
        sa.Column("row_index", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(length=255), nullable=True),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("score_satisfaction_overall", sa.Integer(), nullable=True),
        sa.Column("score_satisfaction_content_volume", sa.Integer(), nullable=True),
        sa.Column(
            "score_satisfaction_content_understanding", sa.Integer(), nullable=True
        ),
        sa.Column(
            "score_satisfaction_content_announcement", sa.Integer(), nullable=True
        ),
        sa.Column("score_satisfaction_instructor_overall", sa.Integer(), nullable=True),
        sa.Column(
            "score_satisfaction_instructor_efficiency", sa.Integer(), nullable=True
        ),
        sa.Column(
            "score_satisfaction_instructor_response", sa.Integer(), nullable=True
        ),
        sa.Column("score_satisfaction_instructor_clarity", sa.Integer(), nullable=True),
        sa.Column("score_self_preparation", sa.Integer(), nullable=True),
        sa.Column("score_self_motivation", sa.Integer(), nullable=True),
        sa.Column("score_self_applicability", sa.Integer(), nullable=True),
        sa.Column("score_recommend_to_friend", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["file_id"], ["uploaded_file.file_id"]),
        sa.ForeignKeyConstraint(["survey_batch_id"], ["survey_batch.id"]),
    )
    op.create_index(
        op.f("ix_survey_response_survey_batch_id"),
        "survey_response",
        ["survey_batch_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_survey_response_account_id"),
        "survey_response",
        ["account_id"],
        unique=False,
    )

    op.create_table(
        "response_comment",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("survey_batch_id", sa.Integer(), nullable=True),
        sa.Column("survey_response_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(length=255), nullable=True),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=True),
        sa.Column("comment_text", sa.Text(), nullable=False),
        sa.Column("llm_category", sa.String(length=50), nullable=True),
        sa.Column("llm_sentiment", sa.String(length=20), nullable=True),
        sa.Column("llm_summary", sa.Text(), nullable=True),
        sa.Column("llm_importance_level", sa.String(length=20), nullable=True),
        sa.Column("llm_importance_score", sa.Float(), nullable=True),
        sa.Column("llm_risk_level", sa.String(length=20), nullable=True),
        sa.Column("processed_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("analysis_version", sa.String(length=20), nullable=True),
        sa.Column("is_important", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["file_id"], ["uploaded_file.file_id"]),
        sa.ForeignKeyConstraint(["survey_batch_id"], ["survey_batch.id"]),
        sa.ForeignKeyConstraint(["survey_response_id"], ["survey_response.id"]),
    )
    op.create_index(
        op.f("ix_response_comment_survey_batch_id"),
        "response_comment",
        ["survey_batch_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_response_comment_account_id"),
        "response_comment",
        ["account_id"],
        unique=False,
    )

    op.create_table(
        "lecture_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("zoom_participants", sa.Integer(), nullable=True),
        sa.Column("recording_views", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id"),
        sa.ForeignKeyConstraint(["file_id"], ["uploaded_file.file_id"]),
    )

    op.create_table(
        "survey_summary",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("survey_batch_id", sa.Integer(), nullable=False),
        sa.Column(
            "analysis_version",
            sa.String(length=20),
            nullable=False,
            server_default="preliminary",
        ),
        sa.Column("score_overall_satisfaction", sa.Float(), nullable=True),
        sa.Column("score_content_volume", sa.Float(), nullable=True),
        sa.Column("score_content_understanding", sa.Float(), nullable=True),
        sa.Column("score_content_announcement", sa.Float(), nullable=True),
        sa.Column("score_instructor_overall", sa.Float(), nullable=True),
        sa.Column("score_instructor_time", sa.Float(), nullable=True),
        sa.Column("score_instructor_qa", sa.Float(), nullable=True),
        sa.Column("score_instructor_speaking", sa.Float(), nullable=True),
        sa.Column("score_self_preparation", sa.Float(), nullable=True),
        sa.Column("score_self_motivation", sa.Float(), nullable=True),
        sa.Column("score_self_future", sa.Float(), nullable=True),
        sa.Column("nps_score", sa.Float(), nullable=True),
        sa.Column("nps_promoters", sa.Integer(), nullable=True),
        sa.Column("nps_passives", sa.Integer(), nullable=True),
        sa.Column("nps_detractors", sa.Integer(), nullable=True),
        sa.Column("nps_total", sa.Integer(), nullable=True),
        sa.Column("responses_count", sa.Integer(), nullable=True),
        sa.Column("comments_count", sa.Integer(), nullable=True),
        sa.Column("important_comments_count", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["survey_batch_id"], ["survey_batch.id"]),
        sa.UniqueConstraint(
            "survey_batch_id",
            "analysis_version",
            name="uq_survey_summary_batch_version",
        ),
    )

    op.create_table(
        "comment_summary",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("survey_batch_id", sa.Integer(), nullable=False),
        sa.Column(
            "analysis_version",
            sa.String(length=20),
            nullable=False,
            server_default="preliminary",
        ),
        sa.Column("sentiment_positive", sa.Integer(), nullable=True),
        sa.Column("sentiment_negative", sa.Integer(), nullable=True),
        sa.Column("sentiment_neutral", sa.Integer(), nullable=True),
        sa.Column("category_lecture_content", sa.Integer(), nullable=True),
        sa.Column("category_lecture_material", sa.Integer(), nullable=True),
        sa.Column("category_operations", sa.Integer(), nullable=True),
        sa.Column("category_other", sa.Integer(), nullable=True),
        sa.Column("importance_low", sa.Integer(), nullable=True),
        sa.Column("importance_medium", sa.Integer(), nullable=True),
        sa.Column("importance_high", sa.Integer(), nullable=True),
        sa.Column("important_comments_count", sa.Integer(), nullable=True),
        sa.Column("comments_count", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["survey_batch_id"], ["survey_batch.id"]),
        sa.UniqueConstraint(
            "survey_batch_id",
            "analysis_version",
            name="uq_comment_summary_batch_version",
        ),
    )


def downgrade() -> None:
    op.drop_table("comment_summary")
    op.drop_table("survey_summary")
    op.drop_table("lecture_metrics")
    op.drop_index(op.f("ix_response_comment_account_id"), table_name="response_comment")
    op.drop_index(
        op.f("ix_response_comment_survey_batch_id"), table_name="response_comment"
    )
    op.drop_table("response_comment")
    op.drop_index(op.f("ix_survey_response_account_id"), table_name="survey_response")
    op.drop_index(
        op.f("ix_survey_response_survey_batch_id"), table_name="survey_response"
    )
    op.drop_table("survey_response")
    op.drop_table("survey_batch")
    op.drop_table("uploaded_file")
    op.drop_table("lecture")
