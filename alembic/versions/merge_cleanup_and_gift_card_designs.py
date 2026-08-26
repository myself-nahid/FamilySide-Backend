"""merge cleanup and gift card design migrations

Revision ID: merge_cleanup_and_gift_card_designs
Revises: cleanup_nan_values, d7f2b2a4a1d3
Create Date: 2026-08-26 00:00:00.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "merge_cleanup_and_gift_card_designs"
down_revision: Union[str, Sequence[str], None] = (
    "cleanup_nan_values",
    "d7f2b2a4a1d3",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass