"""add html_path to templates

Revision ID: 0ec82046918a
Revises: bc1ddeece32f
Create Date: 2026-05-29 19:48:14.755981

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0ec82046918a'
down_revision: Union[str, None] = 'bc1ddeece32f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("templates", sa.Column("html_path", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("templates", "html_path")

