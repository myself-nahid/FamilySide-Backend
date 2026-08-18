"""cleanup nan values

Revision ID: cleanup_nan_values
Revises: add_category_icon_url
Create Date: 2026-08-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'cleanup_nan_values'
down_revision = 'add_category_icon_url'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Convert text 'nan' (case-insensitive) to NULL in description
    op.execute(
        """
        UPDATE platform_items
        SET description = NULL
        WHERE description IS NOT NULL AND lower(trim(description)) = 'nan';
        """
    )

    # Replace numeric NaN in price with 0
    op.execute(
        """
        UPDATE platform_items
        SET price = 0
        WHERE price IS NOT NULL AND isnan(price);
        """
    )


def downgrade() -> None:
    # Irreversible: previous NaN/text values cannot be recovered reliably
    pass
