"""Solicitudes de prendas y token de seguimiento

Revision ID: c5f2b8d41a37
Revises: a3d9c7e15f62
Create Date: 2026-11-15 20:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c5f2b8d41a37'
down_revision = 'a3d9c7e15f62'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('solicitudes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('folio', sa.String(length=20), nullable=False),
    sa.Column('estado', sa.String(length=20), nullable=False),
    sa.Column('origen', sa.String(length=20), nullable=False),
    sa.Column('fecha_deseada', sa.Date(), nullable=True),
    sa.Column('fecha_entrega', sa.Date(), nullable=True),
    sa.Column('notas', sa.Text(), nullable=True),
    sa.Column('respuesta', sa.Text(), nullable=True),
    sa.Column('creado_en', sa.DateTime(), nullable=False),
    sa.Column('respondida_en', sa.DateTime(), nullable=True),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=True),
    sa.Column('atendida_por_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id']),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['atendida_por_id'], ['usuarios.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('folio')
    )
    op.create_index('ix_solicitudes_estado', 'solicitudes', ['estado'])

    op.create_table('solicitud_lineas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('solicitud_id', sa.Integer(), nullable=False),
    sa.Column('diseno_id', sa.Integer(), nullable=True),
    sa.Column('descripcion', sa.String(length=200), nullable=False),
    sa.Column('cantidad', sa.Integer(), nullable=False),
    sa.Column('tallas', sa.String(length=100), nullable=True),
    sa.Column('colores', sa.String(length=100), nullable=True),
    sa.Column('medidas', sa.String(length=500), nullable=True),
    sa.Column('precio_unitario', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.ForeignKeyConstraint(['solicitud_id'], ['solicitudes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['diseno_id'], ['disenos.id']),
    sa.PrimaryKeyConstraint('id')
    )

    with op.batch_alter_table('pedidos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('solicitud_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_pedidos_solicitud_id', 'solicitudes', ['solicitud_id'], ['id'])

    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('token_seguimiento', sa.String(length=20), nullable=True))
        batch_op.create_unique_constraint('uq_usuarios_token_seguimiento', ['token_seguimiento'])


def downgrade():
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.drop_constraint('uq_usuarios_token_seguimiento', type_='unique')
        batch_op.drop_column('token_seguimiento')

    with op.batch_alter_table('pedidos', schema=None) as batch_op:
        batch_op.drop_constraint('fk_pedidos_solicitud_id', type_='foreignkey')
        batch_op.drop_column('solicitud_id')

    op.drop_table('solicitud_lineas')
    op.drop_index('ix_solicitudes_estado', table_name='solicitudes')
    op.drop_table('solicitudes')
