"""Drop legacy ``use_tls`` / ``use_ssl`` columns from smtpservers.

``tls_mode`` ('none' | 'starttls' | 'ssl') has been the source of truth
for a while; the bools were kept in lockstep purely as back-compat for
external callers. The API now rejects them outright, the engine and
service layer no longer read them, and the SQLAlchemy model has dropped
them. This migration removes them from the database to match.

Backfill: the previous ``set_tls_mode`` always wrote ``tls_mode`` in
lockstep with the bools, so the source-of-truth column already has the
right value on every existing row — no data conversion needed before
the drop.

Revision ID: c9d4e8b1a7f2
Revises: b8e4a2f1c9d6
Create Date: 2026-05-21 13:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d4e8b1a7f2'
down_revision: Union[str, None] = 'b8e4a2f1c9d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Defensive backfill for any row where tls_mode somehow ended up
    # NULL — the old setter should have kept it in sync, but old rows
    # predating the tls_mode column might exist.
    smtpservers = sa.table(
        'smtpservers',
        sa.column('tls_mode', sa.String),
        sa.column('use_ssl', sa.Boolean),
        sa.column('use_tls', sa.Boolean),
    )
    bind = op.get_bind()
    bind.execute(
        smtpservers.update()
        .where(smtpservers.c.tls_mode.is_(None))
        .where(smtpservers.c.use_ssl.is_(True))
        .values(tls_mode='ssl')
    )
    bind.execute(
        smtpservers.update()
        .where(smtpservers.c.tls_mode.is_(None))
        .where(smtpservers.c.use_tls.is_(True))
        .values(tls_mode='starttls')
    )
    bind.execute(
        smtpservers.update()
        .where(smtpservers.c.tls_mode.is_(None))
        .values(tls_mode='none')
    )

    # SQLite needs batch mode to drop columns.
    with op.batch_alter_table('smtpservers') as batch_op:
        batch_op.alter_column('tls_mode', nullable=False)
        batch_op.drop_column('use_tls')
        batch_op.drop_column('use_ssl')


def downgrade() -> None:
    with op.batch_alter_table('smtpservers') as batch_op:
        batch_op.add_column(sa.Column('use_tls', sa.Boolean(), server_default='1'))
        batch_op.add_column(sa.Column('use_ssl', sa.Boolean(), server_default='0'))
        batch_op.alter_column('tls_mode', nullable=True)

    # Reverse-derive the bools from tls_mode so old readers still work.
    smtpservers = sa.table(
        'smtpservers',
        sa.column('tls_mode', sa.String),
        sa.column('use_ssl', sa.Boolean),
        sa.column('use_tls', sa.Boolean),
    )
    bind = op.get_bind()
    bind.execute(
        smtpservers.update()
        .where(smtpservers.c.tls_mode == 'ssl')
        .values(use_ssl=True, use_tls=False)
    )
    bind.execute(
        smtpservers.update()
        .where(smtpservers.c.tls_mode == 'starttls')
        .values(use_ssl=False, use_tls=True)
    )
    bind.execute(
        smtpservers.update()
        .where(smtpservers.c.tls_mode == 'none')
        .values(use_ssl=False, use_tls=False)
    )
