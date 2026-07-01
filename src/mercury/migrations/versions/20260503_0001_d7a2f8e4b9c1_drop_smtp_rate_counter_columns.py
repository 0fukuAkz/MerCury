"""Drop volatile rate-counter columns from smtpservers.

The ``current_minute_count`` and ``current_hour_count`` columns were
persisted-but-unused: only ``SMTPRepository.update_rate_counts`` wrote to
them, and nothing in src/ ever called that method. The actual rate
limiting is enforced in-memory on the engine's ``SMTPServerConfig``
runtime fields, which reset every minute/hour anyway.

Removing them eliminates write-amplification on the hot send path and
removes one source of state divergence between processes (each worker
had its own in-memory counter; persisting one of them to DB was
nonsensical).

Revision ID: d7a2f8e4b9c1
Revises: c4f8e2b1a3d6
Create Date: 2026-05-03 00:01:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7a2f8e4b9c1'
down_revision: Union[str, None] = 'c4f8e2b1a3d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite needs batch mode to drop columns.
    with op.batch_alter_table('smtpservers') as batch_op:
        batch_op.drop_column('current_minute_count')
        batch_op.drop_column('current_hour_count')


def downgrade() -> None:
    with op.batch_alter_table('smtpservers') as batch_op:
        batch_op.add_column(sa.Column('current_minute_count', sa.Integer(), server_default='0'))
        batch_op.add_column(sa.Column('current_hour_count', sa.Integer(), server_default='0'))
