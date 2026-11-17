"""Flujo de aprobación: tramos de precio por cantidad, condiciones y vigencia de cotización.

- Nueva tabla solicitud_tramos (rebajas por volumen de cada prenda).
- La solicitud guarda condiciones de cambio, etiquetas, vigencia y las fechas de decisión.
- Datos existentes: «confirmada» pasa a «aprobada» (con su precio como tramo base)
  y «rechazada» a «denegada».

Revision ID: e8b3a65f17c4
Revises: c5f2b8d41a37
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = "e8b3a65f17c4"
down_revision = "c5f2b8d41a37"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "solicitud_tramos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("linea_id", sa.Integer(), nullable=False),
        sa.Column("desde_cantidad", sa.Integer(), nullable=False),
        sa.Column("precio_unitario", sa.Numeric(10, 2), nullable=False),
        sa.ForeignKeyConstraint(["linea_id"], ["solicitud_lineas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("linea_id", "desde_cantidad", name="uq_tramo_linea_desde"),
    )
    with op.batch_alter_table("solicitudes") as batch:
        batch.add_column(sa.Column("condiciones", sa.Text(), nullable=True))
        batch.add_column(sa.Column("etiquetas", sa.String(200), nullable=True))
        batch.add_column(sa.Column("motivo_cliente", sa.String(500), nullable=True))
        batch.add_column(sa.Column("aprobada_en", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("vence_en", sa.Date(), nullable=True))
        batch.add_column(sa.Column("decidida_en", sa.DateTime(), nullable=True))

    # Datos existentes del flujo anterior (confirmar → convertir)
    op.execute(
        "INSERT INTO solicitud_tramos (linea_id, desde_cantidad, precio_unitario) "
        "SELECT id, 1, precio_unitario FROM solicitud_lineas WHERE precio_unitario IS NOT NULL"
    )
    op.execute(
        "UPDATE solicitudes SET estado = 'aprobada', aprobada_en = respondida_en, "
        "vence_en = date(COALESCE(respondida_en, CURRENT_TIMESTAMP), '+15 days') "
        "WHERE estado = 'confirmada'"
    )
    op.execute("UPDATE solicitudes SET estado = 'denegada' WHERE estado = 'rechazada'")


def downgrade():
    op.execute("UPDATE solicitudes SET estado = 'confirmada' WHERE estado = 'aprobada'")
    op.execute("UPDATE solicitudes SET estado = 'rechazada' WHERE estado = 'denegada'")
    with op.batch_alter_table("solicitudes") as batch:
        batch.drop_column("decidida_en")
        batch.drop_column("vence_en")
        batch.drop_column("aprobada_en")
        batch.drop_column("motivo_cliente")
        batch.drop_column("etiquetas")
        batch.drop_column("condiciones")
    op.drop_table("solicitud_tramos")
