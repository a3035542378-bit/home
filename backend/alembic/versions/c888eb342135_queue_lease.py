"""队列租约、重试历史和 Outbox。"""
import sqlalchemy as sa

from alembic import op

revision = "c888eb342135"
down_revision = "733e680fde79"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("task_execution") as batch:
        batch.add_column(sa.Column("parent_execution_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("business_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("schedule_key", sa.String(180), nullable=True))
        batch.add_column(sa.Column("worker_id", sa.String(128), nullable=True))
        batch.add_column(sa.Column("lease_token", sa.String(36), nullable=True))
        batch.add_column(sa.Column("lease_until", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("dlq_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_execution_status_lease", ["status", "lease_until"])
        batch.create_unique_constraint("uq_task_execution_parent_execution_id", ["parent_execution_id"])
        batch.create_unique_constraint("uq_task_execution_schedule_key", ["schedule_key"])
        batch.create_foreign_key("fk_task_execution_parent_execution_id_task_execution", "task_execution", ["parent_execution_id"], ["execution_id"])
    op.create_table("task_outbox",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("execution_id", sa.String(36), sa.ForeignKey("task_execution.execution_id"), nullable=False, unique=True),
        sa.Column("job_id", sa.String(36), nullable=False, unique=True),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
    )
    op.create_index("ix_task_outbox_available_at", "task_outbox", ["available_at"])


def downgrade():
    op.drop_table("task_outbox")
    with op.batch_alter_table("task_execution") as batch:
        batch.drop_constraint("fk_task_execution_parent_execution_id_task_execution", type_="foreignkey")
        batch.drop_constraint("uq_task_execution_parent_execution_id", type_="unique")
        batch.drop_constraint("uq_task_execution_schedule_key", type_="unique")
        batch.drop_index("ix_execution_status_lease")
        batch.drop_column("dlq_at")
        batch.drop_column("heartbeat_at")
        batch.drop_column("lease_until")
        batch.drop_column("lease_token")
        batch.drop_column("worker_id")
        batch.drop_column("schedule_key")
        batch.drop_column("business_date")
        batch.drop_column("parent_execution_id")
