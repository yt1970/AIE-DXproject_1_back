"""add_analysis_version_fields

Revision ID: b2f3d8e9a7c1
Revises: 812e498f2dae
Create Date: 2025-11-28 15:16:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2f3d8e9a7c1'
down_revision: Union[str, None] = '812e498f2dae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add analysis_version fields to response_comments, survey_summaries, and comment_summaries."""
    
    # Add analysis_version to response_comments
    with op.batch_alter_table('response_comments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('analysis_version', sa.String(length=20), nullable=True))
    
    # Add analysis_version to survey_summaries
    with op.batch_alter_table('survey_summaries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('analysis_version', sa.String(length=20), nullable=False, server_default='preliminary'))
    
    # Add analysis_version to comment_summaries
    with op.batch_alter_table('comment_summaries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('analysis_version', sa.String(length=20), nullable=False, server_default='preliminary'))


def downgrade() -> None:
    """Remove analysis_version fields."""
    
    # Remove from comment_summaries
    with op.batch_alter_table('comment_summaries', schema=None) as batch_op:
        batch_op.drop_column('analysis_version')
    
    # Remove from survey_summaries
    with op.batch_alter_table('survey_summaries', schema=None) as batch_op:
        batch_op.drop_column('analysis_version')
    
    # Remove from response_comments
    with op.batch_alter_table('response_comments', schema=None) as batch_op:
        batch_op.drop_column('analysis_version')
