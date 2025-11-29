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
        "lectures",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("course_name", sa.String(length=255), nullable=False),
        sa.Column("academic_year", sa.Integer(), nullable=True),
        sa.Column("period", sa.String(length=100), nullable=False),
        sa.Column("term", sa.String(length=50), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("session", sa.String(length=50), nullable=True),
        sa.Column("lecture_date", sa.Date(), nullable=True),
        sa.Column("instructor_name", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("category", sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "name",
            "academic_year",
            "term",
            "session",
            "lecture_date",
            name="uq_lecture_identity",
        ),
    )

    op.create_table(
        "uploaded_files",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("course_name", sa.String(length=255), nullable=False),
        sa.Column("lecture_date", sa.Date(), nullable=False),
        sa.Column("lecture_number", sa.Integer(), nullable=False),
        sa.Column("academic_year", sa.String(length=10), nullable=True),
        sa.Column("period", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("s3_key", sa.String(length=512), nullable=True),
        sa.Column("uploaded_at", sa.TIMESTAMP(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("total_rows", sa.Integer(), nullable=True),
        sa.Column("processed_rows", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.String(length=255), nullable=True),
        sa.Column(
            "lecture_id", sa.Integer(), sa.ForeignKey("lectures.id"), nullable=True
        ),
        sa.Column("processing_started_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("processing_completed_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("finalized_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "course_name",
            "lecture_date",
            "lecture_number",
            name="uq_course_lecture_instance",
        ),
    )

    op.create_table(
        "survey_batches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uploaded_file_id", sa.Integer(), nullable=False),
        sa.Column(
            "lecture_id", sa.Integer(), sa.ForeignKey("lectures.id"), nullable=True
        ),
        sa.Column("course_name", sa.String(length=255), nullable=False),
        sa.Column("lecture_date", sa.Date(), nullable=False),
        sa.Column("lecture_number", sa.Integer(), nullable=False),
        sa.Column("academic_year", sa.String(length=10), nullable=True),
        sa.Column("period", sa.String(length=100), nullable=True),
        sa.Column("batch_type", sa.String(length=20), nullable=False, server_default="preliminary"),
        sa.Column("zoom_participants", sa.Integer(), nullable=True),
        sa.Column("recording_views", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("uploaded_at", sa.TIMESTAMP(), nullable=False),
        sa.Column("processing_started_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("processing_completed_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("finalized_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("total_responses", sa.Integer(), nullable=True),
        sa.Column("total_comments", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uploaded_file_id"),
        sa.UniqueConstraint(
            "course_name",
            "lecture_date",
            "lecture_number",
            name="uq_survey_batch_identity",
        ),
        sa.ForeignKeyConstraint(["uploaded_file_id"], ["uploaded_files.id"]),
    )

    op.create_table(
        "survey_responses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uploaded_file_id", sa.Integer(), nullable=False),
        sa.Column("survey_batch_id", sa.Integer(), nullable=True),
        sa.Column("row_index", sa.Integer(), nullable=True),
        sa.Column("student_attribute", sa.String(length=50), nullable=False),
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
        sa.Column("score_instructor_time", sa.Integer(), nullable=True),
        sa.Column("score_instructor_qa", sa.Integer(), nullable=True),
        sa.Column("score_instructor_speaking", sa.Integer(), nullable=True),
        sa.Column("score_self_future", sa.Integer(), nullable=True),
        sa.Column("score_recommend_friend", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["uploaded_file_id"], ["uploaded_files.id"]),
        sa.ForeignKeyConstraint(["survey_batch_id"], ["survey_batches.id"]),
    )
    op.create_index(
        op.f("ix_survey_responses_survey_batch_id"),
        "survey_responses",
        ["survey_batch_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_survey_responses_account_id"),
        "survey_responses",
        ["account_id"],
        unique=False,
    )

    op.create_table(
        "response_comments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uploaded_file_id", sa.Integer(), nullable=True),
        sa.Column("survey_batch_id", sa.Integer(), nullable=True),
        sa.Column("survey_response_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.String(length=255), nullable=True),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("question_type", sa.String(length=50), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=True),
        sa.Column("comment_text", sa.Text(), nullable=False),
        sa.Column("llm_category", sa.String(length=50), nullable=True),
        sa.Column("llm_sentiment", sa.String(length=20), nullable=True),
        sa.Column("llm_summary", sa.Text(), nullable=True),
        sa.Column("llm_importance_level", sa.String(length=20), nullable=True),
        sa.Column("llm_importance_score", sa.Float(), nullable=True),
        sa.Column("llm_risk_level", sa.String(length=20), nullable=True),
        sa.Column("llm_is_abusive", sa.Boolean(), nullable=True),
        sa.Column("is_analyzed", sa.Boolean(), nullable=True),
        sa.Column("processed_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("analysis_version", sa.String(length=20), nullable=True),
        sa.Column("is_important", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["uploaded_file_id"], ["uploaded_files.id"]),
        sa.ForeignKeyConstraint(["survey_batch_id"], ["survey_batches.id"]),
        sa.ForeignKeyConstraint(["survey_response_id"], ["survey_responses.id"]),
    )
    op.create_index(
        op.f("ix_response_comments_survey_batch_id"),
        "response_comments",
        ["survey_batch_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_response_comments_account_id"),
        "response_comments",
        ["account_id"],
        unique=False,
    )

    op.create_table(
        "lecture_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uploaded_file_id", sa.Integer(), nullable=False),
        sa.Column("zoom_participants", sa.Integer(), nullable=True),
        sa.Column("recording_views", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uploaded_file_id"),
        sa.ForeignKeyConstraint(["uploaded_file_id"], ["uploaded_files.id"]),
    )

    op.create_table(
        "survey_summaries",
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
        sa.Column("student_attribute", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("nps_score", sa.Float(), nullable=True),
        sa.Column("nps_promoters", sa.Integer(), nullable=True),
        sa.Column("nps_passives", sa.Integer(), nullable=True),
        sa.Column("nps_detractors", sa.Integer(), nullable=True),
        sa.Column("nps_total", sa.Integer(), nullable=True),
        sa.Column("response_count", sa.Integer(), nullable=True),
        sa.Column("comments_count", sa.Integer(), nullable=True),
        sa.Column("important_comments_count", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["survey_batch_id"], ["survey_batches.id"]),
        sa.UniqueConstraint(
            "survey_batch_id",
            "analysis_version",
            "student_attribute",
            name="uq_survey_summary_batch_version",
        ),
    )

    op.create_table(
        "comment_summaries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("survey_batch_id", sa.Integer(), nullable=False),
        sa.Column(
            "analysis_version",
            sa.String(length=20),
            nullable=False,
            server_default="preliminary",
        ),
        sa.Column("student_attribute", sa.String(length=50), nullable=False, server_default="ALL"),
        sa.Column("analysis_type", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=50), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["survey_batch_id"], ["survey_batches.id"]),
        sa.UniqueConstraint(
            "survey_batch_id",
            "analysis_version",
            "student_attribute",
            "analysis_type",
            "label",
            name="uq_comment_summary_entry",
        ),
    )

    op.create_table(
        "score_distributions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("survey_batch_id", sa.Integer(), nullable=False),
        sa.Column("student_attribute", sa.String(length=50), nullable=False),
        sa.Column("question_key", sa.String(length=50), nullable=False),
        sa.Column("score_value", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "survey_batch_id",
            "student_attribute",
            "question_key",
            "score_value",
            name="uq_score_distribution_entry",
        ),
        sa.ForeignKeyConstraint(["survey_batch_id"], ["survey_batches.id"]),
    )


def downgrade() -> None:
    op.drop_table("comment_summaries")
    op.drop_table("score_distributions")
    op.drop_table("survey_summaries")
    op.drop_table("lecture_metrics")
    op.drop_index(op.f("ix_response_comments_account_id"), table_name="response_comments")
    op.drop_index(
        op.f("ix_response_comments_survey_batch_id"), table_name="response_comments"
    )
    op.drop_table("response_comments")
    op.drop_index(op.f("ix_survey_responses_account_id"), table_name="survey_responses")
    op.drop_index(
        op.f("ix_survey_responses_survey_batch_id"), table_name="survey_responses"
    )
    op.drop_table("survey_responses")
    op.drop_table("survey_batches")
    op.drop_table("uploaded_files")
    op.drop_table("lectures")
