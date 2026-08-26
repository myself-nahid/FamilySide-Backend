"""gift_business_link_and_design_occasion

Revision ID: d7f2b2a4a1d3
Revises: e1132fca63d7
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7f2b2a4a1d3'
down_revision: Union[str, Sequence[str], None] = 'e1132fca63d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('platform_items', sa.Column('linked_activity_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_platform_items_linked_activity_id_platform_items',
        'platform_items',
        'platform_items',
        ['linked_activity_id'],
        ['id'],
        ondelete='SET NULL'
    )

    op.add_column('gift_card_designs', sa.Column('occasion', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_constraint('fk_platform_items_linked_activity_id_platform_items', 'platform_items', type_='foreignkey')
    op.drop_column('platform_items', 'linked_activity_id')

    op.drop_column('gift_card_designs', 'occasion')
