"""add async processing columns

Revision ID: 1f9ed4bcbe87
Revises: 6185d09e3ea8
Create Date: 2025-10-20 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1f9ed4bcbe87"
down_revision: Union[str, None] = "6185d09e3ea8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # These columns are already included in the initial migration (6185d09e3ea8)
    # No changes needed - this migration is now a no-op
    pass


def downgrade() -> None:
    # These columns are already included in the initial migration (6185d09e3ea8)
    # No changes needed - this migration is now a no-op
    pass
