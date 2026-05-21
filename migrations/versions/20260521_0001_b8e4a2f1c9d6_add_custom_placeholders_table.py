"""Add custom_placeholders table.

Stores operator-defined global placeholders. Merged into the
PlaceholderProcessor at campaign-configure time. ``name`` is unique
because duplicate entries would race-condition resolve and confuse the
operator about which value is winning.

Revision ID: b8e4a2f1c9d6
Revises: a1c5d9e3f721
Create Date: 2026-05-21 00:01:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8e4a2f1c9d6'
down_revision: Union[str, None] = 'a1c5d9e3f721'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'custom_placeholders',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('value', sa.Text(), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint('name', name='uq_custom_placeholders_name'),
    )


def downgrade() -> None:
    op.drop_table('custom_placeholders')
