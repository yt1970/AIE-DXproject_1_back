"""merge_heads

Revision ID: 190a9ff60554
Revises: 4c84b4fb6cbc, a1b2c3d4e5f6
Create Date: 2025-11-28 14:39:56.387794

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '190a9ff60554'
down_revision: Union[str, None] = ('4c84b4fb6cbc', 'a1b2c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
