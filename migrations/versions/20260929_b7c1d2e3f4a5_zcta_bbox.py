"""zcta bounding boxes for map viewport queries

Revision ID: b7c1d2e3f4a5
Revises: 453af1235dc8
Create Date: 2026-09-29 13:00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c1d2e3f4a5'
down_revision: Union[str, None] = '453af1235dc8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('zcta_markets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bbox_min_lon', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('bbox_min_lat', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('bbox_max_lon', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('bbox_max_lat', sa.Float(), nullable=True))
        batch_op.create_index(
            'ix_zcta_markets_bbox', ['bbox_min_lat', 'bbox_max_lat', 'bbox_min_lon'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('zcta_markets', schema=None) as batch_op:
        batch_op.drop_index('ix_zcta_markets_bbox')
        batch_op.drop_column('bbox_max_lat')
        batch_op.drop_column('bbox_max_lon')
        batch_op.drop_column('bbox_min_lat')
        batch_op.drop_column('bbox_min_lon')
