"""Cotizaciones, órdenes de compra, costos, control de calidad, notificaciones y bitácora

Revision ID: a3d9c7e15f62
Revises: 8c1f4a6e2b90
Create Date: 2026-11-09 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3d9c7e15f62'
down_revision = '8c1f4a6e2b90'
branch_labels = None
depends_on = None


def upgrade():
    # --- Costos, proveedor habitual y fotos -------------------------------
    with op.batch_alter_table('insumos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('costo_unitario', sa.Numeric(precision=10, scale=2),
                                      nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('proveedor_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('imagen', sa.String(length=255), nullable=True))
        batch_op.create_foreign_key('fk_insumos_proveedor_id', 'proveedores', ['proveedor_id'], ['id'])

    with op.batch_alter_table('disenos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('precio_venta', sa.Numeric(precision=10, scale=2), nullable=True))
        batch_op.add_column(sa.Column('costo_mano_obra', sa.Numeric(precision=10, scale=2),
                                      nullable=False, server_default='0'))

    # --- Cotizaciones ------------------------------------------------------
    op.create_table('cotizaciones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('folio', sa.String(length=20), nullable=False),
    sa.Column('fecha', sa.Date(), nullable=False),
    sa.Column('validez_dias', sa.Integer(), nullable=False),
    sa.Column('fecha_entrega', sa.Date(), nullable=True),
    sa.Column('estado', sa.String(length=20), nullable=False),
    sa.Column('descuento_pct', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('iva_pct', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('condiciones', sa.Text(), nullable=True),
    sa.Column('notas', sa.Text(), nullable=True),
    sa.Column('creado_en', sa.DateTime(), nullable=True),
    sa.Column('respondida_en', sa.DateTime(), nullable=True),
    sa.Column('cliente_id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('folio')
    )
    op.create_table('cotizacion_lineas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('descripcion', sa.String(length=200), nullable=False),
    sa.Column('tallas', sa.String(length=100), nullable=True),
    sa.Column('cantidad', sa.Integer(), nullable=False),
    sa.Column('precio_unitario', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('cotizacion_id', sa.Integer(), nullable=False),
    sa.Column('diseno_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['cotizacion_id'], ['cotizaciones.id'], ),
    sa.ForeignKeyConstraint(['diseno_id'], ['disenos.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    with op.batch_alter_table('pedidos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('precio_unitario', sa.Numeric(precision=10, scale=2), nullable=True))
        batch_op.add_column(sa.Column('cotizacion_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_pedidos_cotizacion_id', 'cotizaciones', ['cotizacion_id'], ['id'])

    # --- Órdenes de compra -------------------------------------------------
    op.create_table('ordenes_compra',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('folio', sa.String(length=20), nullable=False),
    sa.Column('estado', sa.String(length=20), nullable=False),
    sa.Column('fecha', sa.DateTime(), nullable=False),
    sa.Column('fecha_esperada', sa.Date(), nullable=True),
    sa.Column('fecha_recepcion', sa.DateTime(), nullable=True),
    sa.Column('notas', sa.Text(), nullable=True),
    sa.Column('proveedor_id', sa.Integer(), nullable=True),
    sa.Column('usuario_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['proveedor_id'], ['proveedores.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('folio')
    )
    op.create_table('orden_compra_lineas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cantidad', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('costo_unitario', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('orden_id', sa.Integer(), nullable=False),
    sa.Column('insumo_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['insumo_id'], ['insumos.id'], ),
    sa.ForeignKeyConstraint(['orden_id'], ['ordenes_compra.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    # --- Control de calidad ------------------------------------------------
    op.create_table('registros_calidad',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('fecha', sa.DateTime(), nullable=False),
    sa.Column('linea', sa.String(length=40), nullable=False),
    sa.Column('tipo', sa.String(length=20), nullable=False),
    sa.Column('categoria', sa.String(length=60), nullable=False),
    sa.Column('cantidad', sa.Integer(), nullable=False),
    sa.Column('descripcion', sa.Text(), nullable=True),
    sa.Column('accion_correctiva', sa.Text(), nullable=True),
    sa.Column('resuelto', sa.Boolean(), nullable=False),
    sa.Column('resuelto_en', sa.DateTime(), nullable=True),
    sa.Column('pedido_id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['pedido_id'], ['pedidos.id'], ),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    # --- Notificaciones ----------------------------------------------------
    op.create_table('notificaciones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tipo', sa.String(length=20), nullable=False),
    sa.Column('nivel', sa.String(length=10), nullable=False),
    sa.Column('titulo', sa.String(length=150), nullable=False),
    sa.Column('mensaje', sa.String(length=300), nullable=True),
    sa.Column('url', sa.String(length=255), nullable=True),
    sa.Column('clave', sa.String(length=120), nullable=False),
    sa.Column('automatica', sa.Boolean(), nullable=False),
    sa.Column('leida', sa.Boolean(), nullable=False),
    sa.Column('creada_en', sa.DateTime(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('usuario_id', 'clave', name='uq_notificacion_usuario_clave')
    )

    # --- Bitácora de auditoría ---------------------------------------------
    op.create_table('auditoria',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('fecha', sa.DateTime(), nullable=False),
    sa.Column('accion', sa.String(length=20), nullable=False),
    sa.Column('entidad', sa.String(length=40), nullable=False),
    sa.Column('entidad_id', sa.Integer(), nullable=True),
    sa.Column('descripcion', sa.String(length=255), nullable=False),
    sa.Column('cambios', sa.Text(), nullable=True),
    sa.Column('ip', sa.String(length=45), nullable=True),
    sa.Column('usuario_id', sa.Integer(), nullable=True),
    sa.Column('usuario_nombre', sa.String(length=100), nullable=True),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('auditoria', schema=None) as batch_op:
        batch_op.create_index('ix_auditoria_fecha', ['fecha'], unique=False)


def downgrade():
    with op.batch_alter_table('auditoria', schema=None) as batch_op:
        batch_op.drop_index('ix_auditoria_fecha')
    op.drop_table('auditoria')
    op.drop_table('notificaciones')
    op.drop_table('registros_calidad')
    op.drop_table('orden_compra_lineas')
    op.drop_table('ordenes_compra')
    with op.batch_alter_table('pedidos', schema=None) as batch_op:
        batch_op.drop_constraint('fk_pedidos_cotizacion_id', type_='foreignkey')
        batch_op.drop_column('cotizacion_id')
        batch_op.drop_column('precio_unitario')
    op.drop_table('cotizacion_lineas')
    op.drop_table('cotizaciones')
    with op.batch_alter_table('disenos', schema=None) as batch_op:
        batch_op.drop_column('costo_mano_obra')
        batch_op.drop_column('precio_venta')
    with op.batch_alter_table('insumos', schema=None) as batch_op:
        batch_op.drop_constraint('fk_insumos_proveedor_id', type_='foreignkey')
        batch_op.drop_column('imagen')
        batch_op.drop_column('proveedor_id')
        batch_op.drop_column('costo_unitario')
