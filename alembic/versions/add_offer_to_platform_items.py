"""Add gift includes to platform items.

Revision ID: add_includes_to_platform_items
Revises: merge_cleanup_and_gift_card_designs
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_includes_to_platform_items"
down_revision: Union[str, Sequence[str], None] = "merge_cleanup_and_gift_card_designs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("platform_items", sa.Column("includes", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("platform_items", "includes")