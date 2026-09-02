"""add confidence and flip level to trades

Instrumentering fra PRD_FLIP_LEVEL_OG_CONFIDENCE del C. Fire nullable kolonner på
``trades``, så Loop A kan se BÅDE hvilken confidence der frembragte en handel og om
handlens præmis (flip level) bortfaldt undervejs. Ingen ændring af handelsadfærd —
kolonnerne skrives, de læses ikke til beslutninger.

Alle nullable: eksisterende rækker forbliver gyldige med NULL (de blev åbnet før
instrumenteringen fandtes, og den confidence kan ikke genskabes bagudrettet).

Revision ID: a3c1d9e4b217
Revises: 7450c4f8f05d
Create Date: 2026-09-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3c1d9e4b217'
down_revision: Union[str, Sequence[str], None] = '7450c4f8f05d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('trades', schema=None) as batch_op:
        batch_op.add_column(sa.Column('confidence', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('flip_level', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('flip_breached_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('flip_breached_before_exit', sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('trades', schema=None) as batch_op:
        batch_op.drop_column('flip_breached_before_exit')
        batch_op.drop_column('flip_breached_at')
        batch_op.drop_column('flip_level')
        batch_op.drop_column('confidence')
