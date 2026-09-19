"""Preserve completed attempts when HR starts a new assessment.

Revision ID: b71f288a4103
Revises: a47e7eab9012
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b71f288a4103"
down_revision: Union[str, Sequence[str], None] = "a47e7eab9012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("assessment_round", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("assessment_results", sa.Column("assessment_round", sa.Integer(), nullable=False, server_default="1"))
    op.create_table(
        "assessment_archives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("assessment_round", sa.Integer(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("turns", sa.JSON(), nullable=False),
        sa.Column("first_opened_at", sa.DateTime(), nullable=True),
        sa.Column("deadline_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("application_id", "assessment_round"),
    )


def downgrade() -> None:
    op.drop_table("assessment_archives")
    op.drop_column("assessment_results", "assessment_round")
    op.drop_column("applications", "assessment_round")
