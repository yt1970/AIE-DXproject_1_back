"""Add NOT NULL constraints for schema compliance

Revision ID: a1b2c3d4e5f6
Revises: 5c5f181bb488
Create Date: 2025-11-28 14:20:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '5c5f181bb488'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add NOT NULL constraints to foreign keys and composite unique columns."""
    
    # Update lectures table - composite unique constraint columns
    with op.batch_alter_table('lectures', schema=None) as batch_op:
        batch_op.alter_column('academic_year',
               existing_type=sa.Integer(),
               nullable=False)
        batch_op.alter_column('term',
               existing_type=sa.String(length=50),
               nullable=False)
        batch_op.alter_column('name',
               existing_type=sa.String(length=255),
               nullable=False)
        batch_op.alter_column('session',
               existing_type=sa.String(length=50),
               nullable=False)
        batch_op.alter_column('lecture_date',
               existing_type=sa.Date(),
               nullable=False)

    # Update survey_batches table - foreign key
    with op.batch_alter_table('survey_batches', schema=None) as batch_op:
        batch_op.alter_column('lecture_id',
               existing_type=sa.Integer(),
               nullable=False)

    # Update survey_responses table - foreign key
    with op.batch_alter_table('survey_responses', schema=None) as batch_op:
        batch_op.alter_column('survey_batch_id',
               existing_type=sa.BigInteger(),
               nullable=False)

    # Update response_comments table - foreign key
    with op.batch_alter_table('response_comments', schema=None) as batch_op:
        batch_op.alter_column('response_id',
               existing_type=sa.BigInteger(),
               nullable=False)

    # Update survey_summaries table - foreign key and NPS counts
    with op.batch_alter_table('survey_summaries', schema=None) as batch_op:
        batch_op.alter_column('survey_batch_id',
               existing_type=sa.BigInteger(),
               nullable=False)
        batch_op.alter_column('promoter_count',
               existing_type=sa.Integer(),
               nullable=False,
               existing_server_default='0')
        batch_op.alter_column('passive_count',
               existing_type=sa.Integer(),
               nullable=False,
               existing_server_default='0')
        batch_op.alter_column('detractor_count',
               existing_type=sa.Integer(),
               nullable=False,
               existing_server_default='0')

    # Update score_distributions table - foreign key
    with op.batch_alter_table('score_distributions', schema=None) as batch_op:
        batch_op.alter_column('survey_batch_id',
               existing_type=sa.BigInteger(),
               nullable=False)

    # Update comment_summaries table - foreign key
    with op.batch_alter_table('comment_summaries', schema=None) as batch_op:
        batch_op.alter_column('survey_batch_id',
               existing_type=sa.BigInteger(),
               nullable=False)


def downgrade() -> None:
    """Remove NOT NULL constraints (revert to nullable)."""
    
    # Revert comment_summaries table
    with op.batch_alter_table('comment_summaries', schema=None) as batch_op:
        batch_op.alter_column('survey_batch_id',
               existing_type=sa.BigInteger(),
               nullable=True)

    # Revert score_distributions table
    with op.batch_alter_table('score_distributions', schema=None) as batch_op:
        batch_op.alter_column('survey_batch_id',
               existing_type=sa.BigInteger(),
               nullable=True)

    # Revert survey_summaries table
    with op.batch_alter_table('survey_summaries', schema=None) as batch_op:
        batch_op.alter_column('detractor_count',
               existing_type=sa.Integer(),
               nullable=True,
               existing_server_default='0')
        batch_op.alter_column('passive_count',
               existing_type=sa.Integer(),
               nullable=True,
               existing_server_default='0')
        batch_op.alter_column('promoter_count',
               existing_type=sa.Integer(),
               nullable=True,
               existing_server_default='0')
        batch_op.alter_column('survey_batch_id',
               existing_type=sa.BigInteger(),
               nullable=True)

    # Revert response_comments table
    with op.batch_alter_table('response_comments', schema=None) as batch_op:
        batch_op.alter_column('response_id',
               existing_type=sa.BigInteger(),
               nullable=True)

    # Revert survey_responses table
    with op.batch_alter_table('survey_responses', schema=None) as batch_op:
        batch_op.alter_column('survey_batch_id',
               existing_type=sa.BigInteger(),
               nullable=True)

    # Revert survey_batches table
    with op.batch_alter_table('survey_batches', schema=None) as batch_op:
        batch_op.alter_column('lecture_id',
               existing_type=sa.Integer(),
               nullable=True)

    # Revert lectures table
    with op.batch_alter_table('lectures', schema=None) as batch_op:
        batch_op.alter_column('lecture_date',
               existing_type=sa.Date(),
               nullable=True)
        batch_op.alter_column('session',
               existing_type=sa.String(length=50),
               nullable=True)
        batch_op.alter_column('name',
               existing_type=sa.String(length=255),
               nullable=True)
        batch_op.alter_column('term',
               existing_type=sa.String(length=50),
               nullable=True)
        batch_op.alter_column('academic_year',
               existing_type=sa.Integer(),
               nullable=True)
