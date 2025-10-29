from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# 修正: models.pyからEnum定義をインポートする
from app.db.models import CommentType, SentimentType


# revision identifiers, used by Alembic.
revision: str = '6185d09e3ea8'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    # --- 2. students (生徒マスタ) ---
    op.create_table(
        "students",
        sa.Column("account_id", sa.String(length=255), nullable=False),
        sa.Column("student_id_alias", sa.String(length=255), nullable=True),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=100), nullable=True),
        sa.Column("school_name", sa.String(length=255), nullable=True),
        sa.Column("faculty", sa.String(length=255), nullable=True),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("account_id"),
    )
    op.create_index(op.f('ix_students_student_id_alias'), 'students', ['student_id_alias'], unique=False)

    # --- 3. lectures (講義マスタ) ---
    op.create_table(
        "lectures",
        sa.Column("lecture_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lecture_name", sa.String(length=255), nullable=False),
        sa.Column("lecture_year", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("lecture_id"),
        sa.UniqueConstraint("lecture_name", "lecture_year", name="uq_lecture_name_year"),
    )

    # --- 4. enrollments (受講登録) ---
    op.create_table(
        "enrollments",
        sa.Column("enrollment_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("student_id", sa.String(length=255), nullable=False),
        sa.Column("lecture_id", sa.Integer(), nullable=False),
        sa.Column("application_type", sa.String(length=100), nullable=True),
        sa.Column("application_type_jp", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(['lecture_id'], ['lectures.lecture_id'], ),
        sa.ForeignKeyConstraint(['student_id'], ['students.account_id'], ),
        sa.PrimaryKeyConstraint("enrollment_id"),
        sa.UniqueConstraint("student_id", "lecture_id", name="uq_student_lecture"),
    )
    op.create_index(op.f('ix_enrollments_lecture_id'), 'enrollments', ['lecture_id'], unique=False)
    op.create_index(op.f('ix_enrollments_student_id'), 'enrollments', ['student_id'], unique=False)

    # --- 5. submissions (評価送信 - 数値データ) ---
    op.create_table(
        "submissions",
        sa.Column("submission_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("enrollment_id", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
        sa.Column("satisfaction_overall", sa.Integer(), nullable=True),
        sa.Column("workload_appropriate", sa.Integer(), nullable=True),
        sa.Column("content_understood", sa.Integer(), nullable=True),
        sa.Column("admin_support_good", sa.Integer(), nullable=True),
        sa.Column("instructor_overall", sa.Integer(), nullable=True),
        sa.Column("instructor_time_efficient", sa.Integer(), nullable=True),
        sa.Column("instructor_q_and_a", sa.Integer(), nullable=True),
        sa.Column("instructor_voice", sa.Integer(), nullable=True),
        sa.Column("self_prepared", sa.Integer(), nullable=True),
        sa.Column("self_motivated", sa.Integer(), nullable=True),
        sa.Column("self_application", sa.Integer(), nullable=True),
        sa.Column("nps_recommend", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['enrollment_id'], ['enrollments.enrollment_id'], ),
        sa.PrimaryKeyConstraint("submission_id"),
    )
    op.create_index(op.f('ix_submissions_enrollment_id'), 'submissions', ['enrollment_id'], unique=False)

    # --- 6. analysis_jobs (ジョブ管理) ---
    op.create_table(
        "analysis_jobs",
        sa.Column("job_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lecture_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, default="PENDING"),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("total_submissions", sa.Integer(), default=0),
        sa.Column("processed_submissions", sa.Integer(), default=0),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(['lecture_id'], ['lectures.lecture_id'], ),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(op.f('ix_analysis_jobs_lecture_id'), 'analysis_jobs', ['lecture_id'], unique=False)

    # --- 7. comments (自由記述) ---
    op.create_table(
        "comments",
        sa.Column("comment_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        # SQLAlchemyが自動で 'CREATE TYPE commenttype AS ENUM(...)' を実行してくれる
        sa.Column("comment_type", sa.Enum(CommentType, name='commenttype'), nullable=False),
        sa.Column("comment_text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['submission_id'], ['submissions.submission_id'], ),
        sa.PrimaryKeyConstraint("comment_id"),
    )
    op.create_index(op.f('ix_comments_submission_id'), 'comments', ['submission_id'], unique=False)

    # --- 8. comment_analyses (分析結果) ---
    op.create_table(
        "comment_analyses",
        sa.Column("analysis_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("comment_id", sa.Integer(), nullable=False),
        sa.Column("is_improvement_needed", sa.Boolean(), nullable=False, default=False),
        sa.Column("is_slanderous", sa.Boolean(), nullable=False, default=False),
        # SQLAlchemyが自動で 'CREATE TYPE sentimenttype AS ENUM(...)' を実行してくれる
        sa.Column("sentiment", sa.Enum(SentimentType, name='sentimenttype'), nullable=True),
        sa.Column("analysis_version", sa.String(length=50), nullable=True),
        sa.Column("analyzed_at", sa.TIMESTAMP(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['comment_id'], ['comments.comment_id'], ),
        sa.PrimaryKeyConstraint("analysis_id"),
        sa.UniqueConstraint("comment_id"),
    )


def downgrade() -> None:
    # --- 削除は子テーブルから親テーブルの順に行う ---
    op.drop_table("comment_analyses")
    op.drop_table("comments")
    op.drop_table("analysis_jobs")
    op.drop_table("submissions")
    op.drop_table("enrollments")
    op.drop_table("lectures")
    op.drop_table("students")

    # 🚨 Enum型の削除 (PostgreSQLの場合) - SQLAlchemyが自動で処理してくれるので、
    #    基本的には手動でのDROPは不要だが、明示的に書く場合はこちら。
    #    ただし、テーブルが型を使用していると依存関係で失敗することがある。
    #    テーブル削除後に実行するのが安全。
    sa.Enum(CommentType, name='commenttype').drop(op.get_bind(), checkfirst=True)
    sa.Enum(SentimentType, name='sentimenttype').drop(op.get_bind(), checkfirst=True)