"""Add icon_url to categories

Revision ID: add_category_icon_url
Revises: e34c5ee69c2b
Create Date: 2026-08-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_category_icon_url'
down_revision = 'e34c5ee69c2b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('categories', sa.Column('icon_url', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('categories', 'icon_url')
