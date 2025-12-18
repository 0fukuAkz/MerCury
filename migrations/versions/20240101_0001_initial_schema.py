"""Initial schema

Revision ID: 0001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create templates table
    op.create_table(
        'templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('html_content', sa.Text(), nullable=True),
        sa.Column('text_content', sa.Text(), nullable=True),
        sa.Column('subject', sa.String(length=500), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True, default=True),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('variables', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_templates_name'), 'templates', ['name'], unique=False)
    
    # Create SMTP servers table
    op.create_table(
        'smtpservers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('port', sa.Integer(), nullable=True, default=587),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('password', sa.String(length=255), nullable=True),
        sa.Column('use_tls', sa.Boolean(), nullable=True, default=True),
        sa.Column('use_ssl', sa.Boolean(), nullable=True, default=False),
        sa.Column('use_auth', sa.Boolean(), nullable=True, default=True),
        sa.Column('timeout', sa.Integer(), nullable=True, default=30),
        sa.Column('from_email', sa.String(length=255), nullable=True),
        sa.Column('from_name', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True, default='active'),
        sa.Column('is_enabled', sa.Boolean(), nullable=True, default=True),
        sa.Column('max_per_hour', sa.Integer(), nullable=True, default=500),
        sa.Column('max_per_minute', sa.Integer(), nullable=True, default=30),
        sa.Column('current_hour_count', sa.Integer(), nullable=True, default=0),
        sa.Column('current_minute_count', sa.Integer(), nullable=True, default=0),
        sa.Column('weight', sa.Float(), nullable=True, default=1.0),
        sa.Column('priority', sa.Integer(), nullable=True, default=0),
        sa.Column('failure_count', sa.Integer(), nullable=True, default=0),
        sa.Column('last_failure_at', sa.String(length=50), nullable=True),
        sa.Column('circuit_open', sa.Boolean(), nullable=True, default=False),
        sa.Column('total_sent', sa.Integer(), nullable=True, default=0),
        sa.Column('total_failed', sa.Integer(), nullable=True, default=0),
        sa.Column('settings', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    
    # Create recipient lists table
    op.create_table(
        'recipientlists',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('source_type', sa.String(length=50), nullable=True),
        sa.Column('source_path', sa.String(length=500), nullable=True),
        sa.Column('total_count', sa.Integer(), nullable=True, default=0),
        sa.Column('valid_count', sa.Integer(), nullable=True, default=0),
        sa.Column('is_validated', sa.Boolean(), nullable=True, default=False),
        sa.Column('is_deduplicated', sa.Boolean(), nullable=True, default=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create campaigns table
    op.create_table(
        'campaigns',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('type', sa.String(length=50), nullable=True, default='marketing'),
        sa.Column('status', sa.String(length=50), nullable=False, default='draft'),
        sa.Column('template_id', sa.Integer(), nullable=True),
        sa.Column('recipient_list_id', sa.Integer(), nullable=True),
        sa.Column('scheduled_at', sa.DateTime(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('total_recipients', sa.Integer(), nullable=True, default=0),
        sa.Column('sent_count', sa.Integer(), nullable=True, default=0),
        sa.Column('delivered_count', sa.Integer(), nullable=True, default=0),
        sa.Column('failed_count', sa.Integer(), nullable=True, default=0),
        sa.Column('queued_count', sa.Integer(), nullable=True, default=0),
        sa.Column('settings', sa.JSON(), nullable=True),
        sa.Column('subjects', sa.JSON(), nullable=True),
        sa.Column('subject_rotation_strategy', sa.String(length=50), nullable=True, default='round_robin'),
        sa.Column('from_email', sa.String(length=255), nullable=True),
        sa.Column('from_name', sa.String(length=255), nullable=True),
        sa.Column('reply_to', sa.String(length=255), nullable=True),
        sa.Column('placeholders', sa.JSON(), nullable=True),
        sa.Column('convert_to_image', sa.Boolean(), nullable=True, default=False),
        sa.Column('convert_to_pdf', sa.Boolean(), nullable=True, default=False),
        sa.Column('enable_qr_code', sa.Boolean(), nullable=True, default=False),
        sa.Column('chunk_size', sa.Integer(), nullable=True, default=10000),
        sa.Column('concurrency', sa.Integer(), nullable=True, default=100),
        sa.Column('pause_between_chunks', sa.Integer(), nullable=True, default=30),
        sa.Column('rate_per_minute', sa.Integer(), nullable=True, default=0),
        sa.Column('rate_per_hour', sa.Integer(), nullable=True, default=0),
        sa.Column('smtp_rotation_strategy', sa.String(length=50), nullable=True, default='weighted'),
        sa.Column('auto_failover', sa.Boolean(), nullable=True, default=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['template_id'], ['templates.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['recipient_list_id'], ['recipientlists.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_campaigns_name'), 'campaigns', ['name'], unique=False)
    op.create_index(op.f('ix_campaigns_status'), 'campaigns', ['status'], unique=False)
    
    # Create recipients table
    op.create_table(
        'recipients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('list_id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('first_name', sa.String(length=100), nullable=True),
        sa.Column('last_name', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True, default='pending'),
        sa.Column('is_valid', sa.Boolean(), nullable=True, default=True),
        sa.Column('custom_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['list_id'], ['recipientlists.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_recipients_email'), 'recipients', ['email'], unique=False)
    
    # Create email logs table
    op.create_table(
        'emaillogs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=True),
        sa.Column('recipient_id', sa.Integer(), nullable=True),
        sa.Column('recipient_email', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, default='pending'),
        sa.Column('correlation_id', sa.String(length=100), nullable=True),
        sa.Column('smtp_server', sa.String(length=100), nullable=True),
        sa.Column('smtp_response', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_type', sa.String(length=100), nullable=True),
        sa.Column('is_transient', sa.Boolean(), nullable=True, default=False),
        sa.Column('attempt_count', sa.Integer(), nullable=True, default=1),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.Column('opened_at', sa.DateTime(), nullable=True),
        sa.Column('clicked_at', sa.DateTime(), nullable=True),
        sa.Column('bounced_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['recipient_id'], ['recipients.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_emaillogs_correlation_id'), 'emaillogs', ['correlation_id'], unique=False)
    op.create_index(op.f('ix_emaillogs_recipient_email'), 'emaillogs', ['recipient_email'], unique=False)
    op.create_index(op.f('ix_emaillogs_status'), 'emaillogs', ['status'], unique=False)
    
    # Create campaign SMTP config junction table
    op.create_table(
        'campaign_smtp_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('smtp_server_id', sa.Integer(), nullable=False),
        sa.Column('weight', sa.Float(), nullable=True, default=1.0),
        sa.Column('priority', sa.Integer(), nullable=True, default=0),
        sa.Column('enabled', sa.Boolean(), nullable=True, default=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['smtp_server_id'], ['smtpservers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('campaign_smtp_configs')
    op.drop_index(op.f('ix_emaillogs_status'), table_name='emaillogs')
    op.drop_index(op.f('ix_emaillogs_recipient_email'), table_name='emaillogs')
    op.drop_index(op.f('ix_emaillogs_correlation_id'), table_name='emaillogs')
    op.drop_table('emaillogs')
    op.drop_index(op.f('ix_recipients_email'), table_name='recipients')
    op.drop_table('recipients')
    op.drop_index(op.f('ix_campaigns_status'), table_name='campaigns')
    op.drop_index(op.f('ix_campaigns_name'), table_name='campaigns')
    op.drop_table('campaigns')
    op.drop_table('recipientlists')
    op.drop_table('smtpservers')
    op.drop_index(op.f('ix_templates_name'), table_name='templates')
    op.drop_table('templates')

