"""Add last_event_ip / last_event_ua / last_event_at to emaillogs.

Backfills geo + UA personalization for recipients who don't carry those
columns in their CSV. The tracking pipeline (web/routes/tracking.py)
writes the most-recent open/click IP+UA into these columns; the
campaign send path looks them up before render so {{location.*}} and
{{ua.*}} placeholders resolve for any recipient who's engaged with a
prior campaign.

Why columns on emaillogs (not a new tracking_events table):
- We only need *last-known* per recipient, not full history.
- Avoids the boot-time race that a fresh table would force on
  multi-instance deploys.
- The data is already keyed by recipient_email — an index on
  (recipient_email, last_event_at DESC) makes the lookup O(log n).

Revision ID: e8b3c1f5a2d9
Revises: d7a2f8e4b9c1
Create Date: 2026-05-09 00:01:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e8b3c1f5a2d9'
down_revision: Union[str, None] = 'd7a2f8e4b9c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable so existing rows stay valid; tracking events fill them
    # going forward. SQLite needs batch mode for index creation against
    # an existing table.
    with op.batch_alter_table('emaillogs') as batch_op:
        batch_op.add_column(sa.Column('last_event_ip', sa.String(length=45), nullable=True))
        batch_op.add_column(sa.Column('last_event_ua', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('last_event_at', sa.DateTime(), nullable=True))

    # Composite index drives the lookup "most recent event for recipient X".
    # Partial-index syntax varies across backends, so we use a plain composite.
    op.create_index(
        'ix_emaillogs_recipient_last_event',
        'emaillogs',
        ['recipient_email', 'last_event_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_emaillogs_recipient_last_event', table_name='emaillogs')
    with op.batch_alter_table('emaillogs') as batch_op:
        batch_op.drop_column('last_event_at')
        batch_op.drop_column('last_event_ua')
        batch_op.drop_column('last_event_ip')
