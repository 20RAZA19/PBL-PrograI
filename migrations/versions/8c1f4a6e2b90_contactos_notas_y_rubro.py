"""Módulo de contactos: notas de comunicación, rubro de proveedores y fechas de alta

Revision ID: 8c1f4a6e2b90
Revises: 5b7e2d9a1c44
Create Date: 2026-10-27 11:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8c1f4a6e2b90'
down_revision = '5b7e2d9a1c44'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clientes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('creado_en', sa.DateTime(), nullable=True))

    with op.batch_alter_table('proveedores', schema=None) as batch_op:
        batch_op.add_column(sa.Column('rubro', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('creado_en', sa.DateTime(), nullable=True))

    op.create_table('notas_contacto',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tipo', sa.String(length=20), nullable=False),
    sa.Column('contenido', sa.Text(), nullable=False),
    sa.Column('fecha', sa.DateTime(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=True),
    sa.Column('cliente_id', sa.Integer(), nullable=True),
    sa.Column('proveedor_id', sa.Integer(), nullable=True),
    sa.Column('pedido_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], ),
    sa.ForeignKeyConstraint(['pedido_id'], ['pedidos.id'], ),
    sa.ForeignKeyConstraint(['proveedor_id'], ['proveedores.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    # Fecha de alta para los registros existentes
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE clientes SET creado_en = CURRENT_TIMESTAMP WHERE creado_en IS NULL"))
    conn.execute(sa.text("UPDATE proveedores SET creado_en = CURRENT_TIMESTAMP WHERE creado_en IS NULL"))


def downgrade():
    op.drop_table('notas_contacto')
    with op.batch_alter_table('proveedores', schema=None) as batch_op:
        batch_op.drop_column('creado_en')
        batch_op.drop_column('rubro')
    with op.batch_alter_table('clientes', schema=None) as batch_op:
        batch_op.drop_column('creado_en')
