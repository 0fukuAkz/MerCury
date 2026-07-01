"""Add tls_mode column to smtpservers and backfill from use_tls/use_ssl.

The previous schema had two booleans — use_tls (STARTTLS) and use_ssl
(implicit SSL on connect). Operators could check both, producing
undefined behavior at connect-time: the engine OR'd them so use_ssl
silently won, even if use_tls=True was the operator's stated intent.

Collapse to a single enum-style column with three legal values:
  - 'none'      — plain SMTP, no encryption
  - 'starttls'  — connect plaintext then STARTTLS (typical port 587)
  - 'ssl'       — implicit TLS on connect (typical port 465)

Backfill priorities, matching the prior OR semantics so existing rows
keep the *effective* transport they had before:
  - use_ssl True             → 'ssl'
  - use_ssl False, use_tls True → 'starttls'
  - both False               → 'none'

use_tls / use_ssl are retained as columns and kept in sync at write
time by the model's tls_mode setter, so any external code that still
reads them sees consistent values. They become derived/legacy fields.

Revision ID: a1c5d9e3f721
Revises: f9c4d8a2b1e3
Create Date: 2026-05-15 00:01:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1c5d9e3f721'
down_revision: Union[str, None] = 'f9c4d8a2b1e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('smtpservers') as batch_op:
        batch_op.add_column(
            sa.Column('tls_mode', sa.String(length=16), nullable=True)
        )

    # Backfill in pure SQL so we don't have to import the model here.
    op.execute(
        """
        UPDATE smtpservers
           SET tls_mode = CASE
             WHEN use_ssl THEN 'ssl'
             WHEN use_tls THEN 'starttls'
             ELSE 'none'
           END
         WHERE tls_mode IS NULL
        """
    )


def downgrade() -> None:
    with op.batch_alter_table('smtpservers') as batch_op:
        batch_op.drop_column('tls_mode')
