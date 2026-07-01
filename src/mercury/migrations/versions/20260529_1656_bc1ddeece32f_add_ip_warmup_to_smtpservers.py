"""Add ip_warmup to smtpservers

Revision ID: bc1ddeece32f
Revises: e4d8a9b2c7f1
Create Date: 2026-05-29 16:56:35.472836

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bc1ddeece32f'
down_revision: Union[str, None] = 'e4d8a9b2c7f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("smtpservers", sa.Column("ip_warmup", sa.Boolean(), nullable=True, server_default="0"))


def downgrade() -> None:
    op.drop_column("smtpservers", "ip_warmup")
