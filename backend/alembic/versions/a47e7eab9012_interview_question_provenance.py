"""Record the focus and sources of each AI interview question.

Revision ID: a47e7eab9012
Revises: dcde8273c8de
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a47e7eab9012"
down_revision: Union[str, Sequence[str], None] = "dcde8273c8de"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("interview_turns", sa.Column("focus_area", sa.String(length=80), nullable=True))
    op.add_column("interview_turns", sa.Column("source_refs", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("interview_turns", "source_refs")
    op.drop_column("interview_turns", "focus_area")
