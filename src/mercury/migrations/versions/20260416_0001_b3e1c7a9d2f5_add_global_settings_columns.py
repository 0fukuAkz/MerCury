"""Add missing global_settings columns

Revision ID: b3e1c7a9d2f5
Revises: a9fac8c2c465
Create Date: 2026-04-16 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e1c7a9d2f5'
down_revision: Union[str, None] = 'a9fac8c2c465'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('global_settings') as batch_op:
        batch_op.add_column(sa.Column('batch_size', sa.Integer(), nullable=True, server_default='1000'))
        batch_op.add_column(sa.Column('default_sender_name', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('default_test_email', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('log_retention_days', sa.Integer(), nullable=True, server_default='30'))
        batch_op.add_column(sa.Column('log_level', sa.String(length=20), nullable=True, server_default='INFO'))
        batch_op.add_column(sa.Column('ui_theme', sa.String(length=20), nullable=True, server_default='dark'))


def downgrade() -> None:
    with op.batch_alter_table('global_settings') as batch_op:
        batch_op.drop_column('ui_theme')
        batch_op.drop_column('log_level')
        batch_op.drop_column('log_retention_days')
        batch_op.drop_column('default_test_email')
        batch_op.drop_column('default_sender_name')
        batch_op.drop_column('batch_size')
