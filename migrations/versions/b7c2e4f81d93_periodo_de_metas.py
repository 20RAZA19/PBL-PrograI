"""Periodo (fecha de inicio y fin) de cada meta.

Revision ID: b7c2e4f81d93
Revises: a4d8e2c6f0b1
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa

revision = "b7c2e4f81d93"
down_revision = "a4d8e2c6f0b1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("metas") as batch:
        batch.add_column(sa.Column("fecha_inicio", sa.Date(), nullable=True))
        batch.add_column(sa.Column("fecha_fin", sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table("metas") as batch:
        batch.drop_column("fecha_fin")
        batch.drop_column("fecha_inicio")
