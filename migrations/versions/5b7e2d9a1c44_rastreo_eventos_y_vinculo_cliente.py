"""Rastreo: eventos_rastreo, vínculo usuario-cliente y sincronización de fases

Revision ID: 5b7e2d9a1c44
Revises: 38cca672fbc0
Create Date: 2026-10-27 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5b7e2d9a1c44'
down_revision = '38cca672fbc0'
branch_labels = None
depends_on = None


FASES = ["Recibido", "En Corte", "En Costura", "Terminado", "En Ruta", "Entregado"]


def upgrade():
    # 1) Vincular usuarios con su empresa cliente
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cliente_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_usuarios_cliente_id', 'clientes', ['cliente_id'], ['id'])

    # 2) Historial de rastreo (línea de tiempo + mapa)
    op.create_table('eventos_rastreo',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('estado', sa.String(length=50), nullable=False),
    sa.Column('fase', sa.Integer(), nullable=False),
    sa.Column('ubicacion', sa.String(length=255), nullable=True),
    sa.Column('latitud', sa.Float(), nullable=True),
    sa.Column('longitud', sa.Float(), nullable=True),
    sa.Column('nota', sa.String(length=255), nullable=True),
    sa.Column('fecha', sa.DateTime(), nullable=False),
    sa.Column('pedido_id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['pedido_id'], ['pedidos.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    # 3) Datos: sincronizar fase_tracking con el estado actual de cada pedido
    conn = op.get_bind()
    for i, nombre in enumerate(FASES, start=1):
        conn.execute(
            sa.text("UPDATE pedidos SET fase_tracking = :fase WHERE estado = :estado"),
            {"fase": i, "estado": nombre},
        )


def downgrade():
    op.drop_table('eventos_rastreo')
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.drop_constraint('fk_usuarios_cliente_id', type_='foreignkey')
        batch_op.drop_column('cliente_id')
