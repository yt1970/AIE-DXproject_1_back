"""add async processing columns

Revision ID: 1f9ed4bcbe87
Revises: ca6c48fd97cc
Create Date: 2025-10-20 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1f9ed4bcbe87"
down_revision: Union[str, None] = "ca6c48fd97cc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "uploaded_file",
        sa.Column("task_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "uploaded_file",
        sa.Column("processing_started_at", sa.TIMESTAMP(), nullable=True),
    )
    op.add_column(
        "uploaded_file",
        sa.Column("processing_completed_at", sa.TIMESTAMP(), nullable=True),
    )
    op.add_column(
        "uploaded_file",
        sa.Column("error_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("uploaded_file", "error_message")
    op.drop_column("uploaded_file", "processing_completed_at")
    op.drop_column("uploaded_file", "processing_started_at")
    op.drop_column("uploaded_file", "task_id")
