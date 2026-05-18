"""Add attachments table.

Stores metadata for reusable file attachments. The payload itself is on
disk under ``<data_dir>/attachments/<stored_name>``; this table only
holds the manifest. ``stored_name`` is unique because it is the disk
basename — collisions would silently overwrite a previous payload.

Revision ID: f9c4d8a2b1e3
Revises: e8b3c1f5a2d9
Create Date: 2026-05-10 00:01:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f9c4d8a2b1e3'
down_revision: Union[str, None] = 'e8b3c1f5a2d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'attachments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('stored_name', sa.String(length=80), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('content_type', sa.String(length=120), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint('stored_name', name='uq_attachments_stored_name'),
    )
    op.create_index('ix_attachments_filename', 'attachments', ['filename'])


def downgrade() -> None:
    op.drop_index('ix_attachments_filename', table_name='attachments')
    op.drop_table('attachments')
