"""Add encoding/obfuscation columns to global_settings

Revision ID: c4f8e2b1a3d6
Revises: b3e1c7a9d2f5
Create Date: 2026-04-16 00:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f8e2b1a3d6'
down_revision: Union[str, None] = 'b3e1c7a9d2f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('global_settings') as batch_op:
        batch_op.add_column(sa.Column('encode_attachments', sa.Boolean(), nullable=True, server_default=sa.false()))
        batch_op.add_column(sa.Column('encode_html_entities', sa.Boolean(), nullable=True, server_default=sa.false()))
        batch_op.add_column(sa.Column('encode_body_base64', sa.Boolean(), nullable=True, server_default=sa.false()))
        batch_op.add_column(sa.Column('encode_unicode_homoglyphs', sa.Boolean(), nullable=True, server_default=sa.false()))
        batch_op.add_column(sa.Column('obfuscate_links', sa.Boolean(), nullable=True, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('global_settings') as batch_op:
        batch_op.drop_column('obfuscate_links')
        batch_op.drop_column('encode_unicode_homoglyphs')
        batch_op.drop_column('encode_body_base64')
        batch_op.drop_column('encode_html_entities')
        batch_op.drop_column('encode_attachments')
