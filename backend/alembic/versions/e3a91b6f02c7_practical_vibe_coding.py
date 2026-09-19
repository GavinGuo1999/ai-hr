"""Add candidate-specific AI coding practical assessment.

Revision ID: e3a91b6f02c7
Revises: d8e7b90c6314
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3a91b6f02c7"
down_revision: Union[str, Sequence[str], None] = "d8e7b90c6314"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assessment_results", sa.Column(
        "practical_score", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("assessment_archives", sa.Column(
        "practical", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table(
        "practical_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("assessment_round", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("best_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("best_breakdown", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("feedback", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("best_submission_path", sa.String(length=500), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("application_id", "assessment_round"),
    )


def downgrade() -> None:
    op.drop_table("practical_tasks")
    op.drop_column("assessment_archives", "practical")
    op.drop_column("assessment_results", "practical_score")
