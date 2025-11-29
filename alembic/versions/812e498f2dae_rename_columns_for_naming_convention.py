"""rename_columns_for_naming_convention

Revision ID: 812e498f2dae
Revises: 190a9ff60554
Create Date: 2025-11-28 14:40:03.205981

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '812e498f2dae'
down_revision: Union[str, None] = '190a9ff60554'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Rename columns to comply with naming conventions:
    - lecture_date → lecture_on (Date columns use _on suffix)
    - llm_sentiment → llm_sentiment_type (Type columns use _type suffix)
    - llm_importance → llm_importance_level (Level columns use _level suffix)
    """
    # Note: SQLite doesn't support ALTER COLUMN RENAME directly in old versions,
    # so we use batch_alter_table for compatibility
    
    # Rename lecture_date to lecture_on in lectures table
    with op.batch_alter_table('lectures', schema=None) as batch_op:
        batch_op.alter_column('lecture_date',
                             new_column_name='lecture_on',
                             existing_type=sa.Date(),
                             existing_nullable=False)
    
    # Rename llm_sentiment to llm_sentiment_type in response_comments table
    with op.batch_alter_table('response_comments', schema=None) as batch_op:
        batch_op.alter_column('llm_sentiment',
                             new_column_name='llm_sentiment_type',
                             existing_type=sa.String(length=20),
                             existing_nullable=True)
    
    # Rename llm_importance to llm_importance_level in response_comments table
    with op.batch_alter_table('response_comments', schema=None) as batch_op:
        batch_op.alter_column('llm_importance',
                             new_column_name='llm_importance_level',
                             existing_type=sa.String(length=10),
                             existing_nullable=True)


def downgrade() -> None:
    """
    Revert column names to original state:
    - lecture_on → lecture_date
    - llm_sentiment_type → llm_sentiment
    - llm_importance_level → llm_importance
    """
    # Revert llm_importance_level to llm_importance
    with op.batch_alter_table('response_comments', schema=None) as batch_op:
        batch_op.alter_column('llm_importance_level',
                             new_column_name='llm_importance',
                             existing_type=sa.String(length=10),
                             existing_nullable=True)
    
    # Revert llm_sentiment_type to llm_sentiment
    with op.batch_alter_table('response_comments', schema=None) as batch_op:
        batch_op.alter_column('llm_sentiment_type',
                             new_column_name='llm_sentiment',
                             existing_type=sa.String(length=20),
                             existing_nullable=True)
    
    # Revert lecture_on to lecture_date
    with op.batch_alter_table('lectures', schema=None) as batch_op:
        batch_op.alter_column('lecture_on',
                             new_column_name='lecture_date',
                             existing_type=sa.Date(),
                             existing_nullable=False)
