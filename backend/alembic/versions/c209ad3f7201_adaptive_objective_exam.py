"""Support one-at-a-time adaptive objective questions.

Revision ID: c209ad3f7201
Revises: b71f288a4103
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c209ad3f7201"
down_revision: Union[str, Sequence[str], None] = "b71f288a4103"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("adaptive_exam", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("applications", sa.Column("adaptive_categories", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("application_questions", sa.Column("target_difficulty", sa.Integer(), nullable=True))
    op.add_column("application_questions", sa.Column("answered_at", sa.DateTime(), nullable=True))
    op.add_column("interview_turns", sa.Column("first_answer_complete", sa.Boolean(), nullable=True))
    op.add_column("interview_turns", sa.Column("answer_gap", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("interview_turns", "answer_gap")
    op.drop_column("interview_turns", "first_answer_complete")
    op.drop_column("application_questions", "answered_at")
    op.drop_column("application_questions", "target_difficulty")
    op.drop_column("applications", "adaptive_categories")
    op.drop_column("applications", "adaptive_exam")
