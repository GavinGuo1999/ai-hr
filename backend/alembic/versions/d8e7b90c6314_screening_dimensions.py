"""Store structured resume screening dimensions.

Revision ID: d8e7b90c6314
Revises: c209ad3f7201
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8e7b90c6314"
down_revision: Union[str, Sequence[str], None] = "c209ad3f7201"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("resume_assessments", sa.Column("dimensions", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("resume_assessments", "dimensions")
