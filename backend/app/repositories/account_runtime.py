from sqlalchemy import func, select

from app.models import Account, Node, TaskExecution


class AccountRuntimeRepository:
    def __init__(self, session):
        self.session = session

    async def snapshot(self, account_id, execution_id, cutoff, now):
        account = (
            (
                await self.session.execute(
                    select(
                        Account.status,
                        Account.node_id,
                        Node.status.label("node_status"),
                    )
                    .outerjoin(Node, Account.node_id == Node.id)
                    .where(
                        Account.id == account_id,
                        Account.deleted_at.is_(None),
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if account is None:
            return None
        current = (
            (
                await self.session.execute(
                    select(
                        TaskExecution.worker_id,
                        TaskExecution.lease_until,
                    ).where(
                        TaskExecution.account_id == account_id,
                        TaskExecution.execution_id == execution_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        worker = "UNASSIGNED"
        if current and current["worker_id"]:
            worker = (
                "LEASE_ACTIVE"
                if current["lease_until"] and current["lease_until"] > now
                else "LEASE_EXPIRED"
            )
        finished = func.coalesce(TaskExecution.end_time, TaskExecution.created_at)
        result = {
            "account_status": account["status"],
            "node_id": account["node_id"],
            "node_status": account["node_status"] or "NOT_CONFIGURED",
            "worker_status": worker,
        }
        latest = []
        for status, name in (
            ("SUCCESS", "last_success_execution"),
            ("FAILED", "last_failed_execution"),
        ):
            row = (
                (
                    await self.session.execute(
                        select(
                            TaskExecution.id.label("_order"),
                            TaskExecution.execution_id,
                            TaskExecution.task_code,
                            TaskExecution.status,
                            finished.label("ended_at"),
                        )
                        .where(
                            TaskExecution.account_id == account_id,
                            TaskExecution.execution_id != execution_id,
                            TaskExecution.status == status,
                            finished >= cutoff,
                            finished <= now,
                        )
                        .order_by(finished.desc(), TaskExecution.id.desc())
                        .limit(1)
                    )
                )
                .mappings()
                .one_or_none()
            )
            result[name] = None
            if row:
                public = dict(row)
                order = public.pop("_order")
                public["ended_at"] = row["ended_at"].isoformat()
                result[name] = public
                latest.append((row["ended_at"], order, row["status"]))
        result["last_execution_status"] = max(latest)[2] if latest else None
        return result
