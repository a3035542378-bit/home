"""创建账号节点任务配置与执行记录"""
import sqlalchemy as sa

from alembic import op

revision = '733e680fde79'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('node',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('adapter_type', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_node')),
    sa.UniqueConstraint('name', name=op.f('uq_node_name'))
    )
    op.create_table('task_definition',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('task_code', sa.String(length=64), nullable=False),
    sa.Column('task_name', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('category', sa.String(length=64), nullable=False),
    sa.Column('default_enabled', sa.Boolean(), nullable=False),
    sa.Column('executor_type', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_task_definition')),
    sa.UniqueConstraint('task_code', name=op.f('uq_task_definition_task_code'))
    )
    op.create_table('account',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('account_no', sa.String(length=128), nullable=False),
    sa.Column('nickname', sa.String(length=128), nullable=False),
    sa.Column('platform', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('online_status', sa.String(length=32), nullable=False),
    sa.Column('node_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=True),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['node_id'], ['node.id'], name=op.f('fk_account_node_id_node'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_account')),
    sa.UniqueConstraint('platform', 'account_no', name=op.f('uq_account_platform'))
    )
    op.create_table('task_config',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('account_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('task_code', sa.String(length=64), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('config_json', sa.JSON(), nullable=False),
    sa.Column('active_execution_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['account.id'], name=op.f('fk_task_config_account_id_account')),
    sa.ForeignKeyConstraint(['task_code'], ['task_definition.task_code'], name=op.f('fk_task_config_task_code_task_definition')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_task_config')),
    sa.UniqueConstraint('account_id', 'task_code', name=op.f('uq_task_config_account_id'))
    )
    op.create_table('task_execution',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('execution_id', sa.String(length=36), nullable=False),
    sa.Column('account_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('task_code', sa.String(length=64), nullable=False),
    sa.Column('trigger_type', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.Column('start_time', sa.DateTime(), nullable=True),
    sa.Column('end_time', sa.DateTime(), nullable=True),
    sa.Column('result_json', sa.JSON(), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('retry_count >= 0', name=op.f('ck_task_execution_retry_nonnegative')),
    sa.ForeignKeyConstraint(['account_id'], ['account.id'], name=op.f('fk_task_execution_account_id_account')),
    sa.ForeignKeyConstraint(['task_code'], ['task_definition.task_code'], name=op.f('fk_task_execution_task_code_task_definition')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_task_execution')),
    sa.UniqueConstraint('execution_id', name=op.f('uq_task_execution_execution_id'))
    )
    op.create_index('ix_execution_account_task', 'task_execution', ['account_id', 'task_code', 'created_at'], unique=False)
    op.create_index('ix_execution_created_status', 'task_execution', ['created_at', 'status'], unique=False)


def downgrade():
    op.drop_index('ix_execution_created_status', table_name='task_execution')
    op.drop_index('ix_execution_account_task', table_name='task_execution')
    op.drop_table('task_execution')
    op.drop_table('task_config')
    op.drop_table('account')
    op.drop_table('task_definition')
    op.drop_table('node')
