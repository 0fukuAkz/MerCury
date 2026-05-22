"""Align emaillogs schema with the current EmailLog model.

The initial schema migration (2024-01-01) created emaillogs with an
older column shape (attempt_count, bounced_at, is_transient,
recipient_id, smtp_server — a single string), and a much shorter
column list than the model carries today. The model grew over time
(subject, from_email, from_name, queued_at, failed_at, retry_count,
max_retries, open_count, click_count, smtp_server_id +
smtp_server_name pair, and the extra_data JSON column whose SQL name
is ``metadata``) — but no migration ever caught the table up.

Local dev hid this because the on-disk SQLite was built via
``Base.metadata.create_all()`` from the current model, which produced
the right shape. CI starts fresh, runs ``alembic upgrade head``, gets
the *old* shape, and 7 tests in test_geo_backfill.py fail because
SQLAlchemy's INSERT lists every model-declared column.

This revision adds the 12 missing columns via plain ``op.add_column``.
We deliberately do NOT use ``op.batch_alter_table`` — SQLite-batch
mode reconstructs the table by copy-rename-swap, and on a table this
wide it trips SQLAlchemy's topological sort with a
``CircularDependencyError``. Plain ``ADD COLUMN`` works fine for
nullable columns without FK constraints.

The FK on smtp_server_id (to smtpservers.id) is declared at the ORM
level via ``ForeignKey()`` on the model — SQLAlchemy relationship
navigation works either way, and SQLite doesn't enforce FKs at the
storage layer unless ``PRAGMA foreign_keys=ON`` is set (it isn't, by
default, in this app's session setup).

The 5 legacy columns (attempt_count, bounced_at, is_transient,
recipient_id, smtp_server) are left in place — SQLAlchemy ignores
them since the model doesn't declare them, and dropping persisted
data is a separate decision.

Revision ID: e4d8a9b2c7f1
Revises: c9d4e8b1a7f2
Create Date: 2026-05-22 08:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e4d8a9b2c7f1'
down_revision: Union[str, None] = 'c9d4e8b1a7f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Each entry is a Column the model declares but the table is missing
# after the existing migration chain runs. All nullable so existing
# rows stay valid; integer counters get server-side defaults so
# downstream code that reads them without checking for NULL doesn't
# crash on legacy rows.
_NEW_COLUMNS = [
    sa.Column('subject', sa.String(length=500), nullable=True),
    sa.Column('from_email', sa.String(length=255), nullable=True),
    sa.Column('from_name', sa.String(length=255), nullable=True),
    sa.Column('smtp_server_id', sa.Integer(), nullable=True),
    sa.Column('smtp_server_name', sa.String(length=100), nullable=True),
    sa.Column('queued_at', sa.DateTime(), nullable=True),
    sa.Column('failed_at', sa.DateTime(), nullable=True),
    sa.Column('retry_count', sa.Integer(), nullable=True, server_default='0'),
    sa.Column('max_retries', sa.Integer(), nullable=True, server_default='3'),
    sa.Column('open_count', sa.Integer(), nullable=True, server_default='0'),
    sa.Column('click_count', sa.Integer(), nullable=True, server_default='0'),
    # Model exposes this as ``extra_data`` but the SQL column name is
    # ``metadata`` — the Python attribute had to be renamed because
    # ``metadata`` is reserved by SQLAlchemy's Declarative API.
    sa.Column('metadata', sa.JSON(), nullable=True),
]


def upgrade() -> None:
    for col in _NEW_COLUMNS:
        op.add_column('emaillogs', col)


def downgrade() -> None:
    for col in reversed(_NEW_COLUMNS):
        op.drop_column('emaillogs', col.name)
