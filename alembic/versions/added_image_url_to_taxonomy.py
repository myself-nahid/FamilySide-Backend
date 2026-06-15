"""Added image_url to categories, subcategories, and tags

Revision ID: taxonomy_images_001
Revises: 4bff37ec7ee5
Create Date: 2026-06-15 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'taxonomy_images_001'
down_revision = '4bff37ec7ee5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add image_url column to categories table
    op.add_column('categories', sa.Column('image_url', sa.String(), nullable=True))
    
    # Add image_url column to sub_categories table
    op.add_column('sub_categories', sa.Column('image_url', sa.String(), nullable=True))
    
    # Add image_url column to tags table
    op.add_column('tags', sa.Column('image_url', sa.String(), nullable=True))


def downgrade() -> None:
    # Drop image_url column from tags table
    op.drop_column('tags', 'image_url')
    
    # Drop image_url column from sub_categories table
    op.drop_column('sub_categories', 'image_url')
    
    # Drop image_url column from categories table
    op.drop_column('categories', 'image_url')
