"""add_dead_letter_queue

Revision ID: 6a8d103842df
Revises: 0001
Create Date: 2025-12-15 07:28:25.034667

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6a8d103842df'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create dead_letters table."""
    op.create_table(
        'dead_letters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recipient', sa.String(length=255), nullable=False),
        sa.Column('subject', sa.String(length=500), nullable=False),
        sa.Column('html_body', sa.Text(), nullable=False),
        sa.Column('from_email', sa.String(length=255), nullable=False),
        sa.Column('from_name', sa.String(length=255), nullable=True),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('correlation_id', sa.String(length=100), nullable=True),
        sa.Column('error_type', sa.String(length=100), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=False),
        sa.Column('smtp_server', sa.String(length=100), nullable=True),
        sa.Column('smtp_response', sa.Text(), nullable=True),
        sa.Column('failed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('additional_data', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for common queries
    op.create_index('ix_dead_letters_recipient', 'dead_letters', ['recipient'])
    op.create_index('ix_dead_letters_campaign_id', 'dead_letters', ['campaign_id'])
    op.create_index('ix_dead_letters_correlation_id', 'dead_letters', ['correlation_id'])
    op.create_index('ix_dead_letters_resolved', 'dead_letters', ['resolved'])
    op.create_index('ix_dead_letters_error_type', 'dead_letters', ['error_type'])
    op.create_index('ix_dead_letters_failed_at', 'dead_letters', ['failed_at'])


def downgrade() -> None:
    """Drop dead_letters table."""
    op.drop_index('ix_dead_letters_failed_at', table_name='dead_letters')
    op.drop_index('ix_dead_letters_error_type', table_name='dead_letters')
    op.drop_index('ix_dead_letters_resolved', table_name='dead_letters')
    op.drop_index('ix_dead_letters_correlation_id', table_name='dead_letters')
    op.drop_index('ix_dead_letters_campaign_id', table_name='dead_letters')
    op.drop_index('ix_dead_letters_recipient', table_name='dead_letters')
    op.drop_table('dead_letters')

