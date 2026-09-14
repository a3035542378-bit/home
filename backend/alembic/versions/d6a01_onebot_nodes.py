"""节点 OneBot 连接配置与健康快照。"""
import sqlalchemy as sa

from alembic import op

revision = "d6a01_onebot_nodes"
down_revision = "c888eb342135"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("node") as batch:
        batch.add_column(sa.Column("onebot_http_url", sa.String(2048), nullable=True))
        batch.add_column(sa.Column("onebot_ws_url", sa.String(2048), nullable=True))
        batch.add_column(sa.Column("secret_ref", sa.String(128), nullable=True))
        batch.add_column(sa.Column("config_revision", sa.Integer(), server_default="1", nullable=False))
        batch.add_column(sa.Column("ws_state", sa.String(32), server_default="UNKNOWN", nullable=False))
        batch.add_column(sa.Column("ws_seen_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("checked_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("node") as batch:
        for name in ("checked_at", "ws_seen_at", "ws_state", "config_revision", "secret_ref", "onebot_ws_url", "onebot_http_url"):
            batch.drop_column(name)
