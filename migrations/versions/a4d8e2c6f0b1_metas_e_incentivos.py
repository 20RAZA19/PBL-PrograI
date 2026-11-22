"""Metas del equipo e incentivos pagados por mes.

Revision ID: a4d8e2c6f0b1
Revises: f1a7c3e9b2d4
Create Date: 2026-11-17
"""
from alembic import op
import sqlalchemy as sa

revision = "a4d8e2c6f0b1"
down_revision = "f1a7c3e9b2d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "metas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("indicador", sa.String(length=40), nullable=False),
        sa.Column("rol", sa.String(length=20), nullable=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=True),
        sa.Column("objetivo", sa.Numeric(12, 2), nullable=False),
        sa.Column("incentivo", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("umbral_parcial", sa.Integer(), nullable=True),
        sa.Column("descripcion", sa.String(length=255), nullable=True),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("creado_en", sa.DateTime(), nullable=False),
        sa.Column("creada_por_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_table(
        "pagos_incentivo",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("meta_id", sa.Integer(), sa.ForeignKey("metas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("meta_nombre", sa.String(length=120), nullable=False),
        sa.Column("anio", sa.Integer(), nullable=False),
        sa.Column("mes", sa.Integer(), nullable=False),
        sa.Column("valor", sa.Numeric(12, 2), nullable=True),
        sa.Column("objetivo", sa.Numeric(12, 2), nullable=False),
        sa.Column("avance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("monto", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("estado", sa.String(length=12), nullable=False, server_default="pendiente"),
        sa.Column("creado_en", sa.DateTime(), nullable=False),
        sa.Column("pagado_en", sa.DateTime(), nullable=True),
        sa.Column("pagado_por_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("usuario_id", "meta_id", "anio", "mes", name="uq_pago_meta_mes"),
    )
    op.create_index("ix_pagos_incentivo_usuario_id", "pagos_incentivo", ["usuario_id"])


def downgrade():
    op.drop_index("ix_pagos_incentivo_usuario_id", table_name="pagos_incentivo")
    op.drop_table("pagos_incentivo")
    op.drop_table("metas")
