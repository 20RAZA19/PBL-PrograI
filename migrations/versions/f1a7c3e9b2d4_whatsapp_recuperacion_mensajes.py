"""Recuperación de contraseña por código y mensajería asistente–cliente.

Revision ID: f1a7c3e9b2d4
Revises: e8b3a65f17c4
Create Date: 2026-11-16
"""
from alembic import op
import sqlalchemy as sa

revision = "f1a7c3e9b2d4"
down_revision = "e8b3a65f17c4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("usuarios") as batch:
        batch.add_column(sa.Column("recuperacion_hash", sa.String(length=256), nullable=True))
        batch.add_column(sa.Column("recuperacion_expira", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("recuperacion_intentos", sa.Integer(), nullable=True))

    op.create_table(
        "conversaciones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asunto", sa.String(length=120), nullable=False),
        sa.Column("cliente_id", sa.Integer(), sa.ForeignKey("clientes.id"), nullable=False),
        sa.Column("creada_por_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("creada_en", sa.DateTime(), nullable=False),
        sa.Column("ultima_actividad", sa.DateTime(), nullable=False),
        sa.Column("guardada", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_conversaciones_cliente_id", "conversaciones", ["cliente_id"])
    op.create_index("ix_conversaciones_ultima_actividad", "conversaciones", ["ultima_actividad"])

    op.create_table(
        "mensajes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversacion_id", sa.Integer(), sa.ForeignKey("conversaciones.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("autor_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("de_cliente", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("creado_en", sa.DateTime(), nullable=False),
        sa.Column("leido", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_mensajes_conversacion_id", "mensajes", ["conversacion_id"])


def downgrade():
    op.drop_index("ix_mensajes_conversacion_id", table_name="mensajes")
    op.drop_table("mensajes")
    op.drop_index("ix_conversaciones_ultima_actividad", table_name="conversaciones")
    op.drop_index("ix_conversaciones_cliente_id", table_name="conversaciones")
    op.drop_table("conversaciones")
    with op.batch_alter_table("usuarios") as batch:
        batch.drop_column("recuperacion_intentos")
        batch.drop_column("recuperacion_expira")
        batch.drop_column("recuperacion_hash")
