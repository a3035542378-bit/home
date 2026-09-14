from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select, update

from app.models import Account, TaskConfig, TaskDefinition, TaskExecution, TaskOutbox
from app.models.common import ExecutionStatus as S
from app.queue.base import TaskJob


class DispatchRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def on_day(day, bounds=None):
        exact = TaskExecution.business_date == day
        if bounds is None:
            return exact
        return or_(exact, and_(TaskExecution.business_date.is_(None),
                               TaskExecution.created_at >= bounds[0],
                               TaskExecution.created_at < bounds[1]))

    async def schedule_execution(self, key):
        return await self.session.scalar(select(TaskExecution).where(TaskExecution.schedule_key == key))

    async def child(self, parent_id):
        return await self.session.scalar(select(TaskExecution).where(
            TaskExecution.parent_execution_id == parent_id,
        ))

    async def latest(self, account_id, code, day, bounds=None):
        return await self.session.scalar(select(TaskExecution).where(
            TaskExecution.account_id == account_id, TaskExecution.task_code == code,
            self.on_day(day, bounds),
        ).order_by(TaskExecution.id.desc()).limit(1))

    async def has_success(self, account_id, code, day, bounds=None):
        return await self.session.scalar(select(TaskExecution.id).where(
            TaskExecution.account_id == account_id, TaskExecution.task_code == code,
            self.on_day(day, bounds), TaskExecution.status == S.SUCCESS,
        ).limit(1)) is not None

    async def create(self, account_id, code, trigger, day, now, parent=None, schedule_key=None,
                     delay=0):
        execution_id = str(uuid4())
        changed = await self.session.execute(update(TaskConfig).where(
            TaskConfig.account_id == account_id, TaskConfig.task_code == code,
            TaskConfig.enabled.is_(True), TaskConfig.active_execution_id.is_(None),
        ).values(active_execution_id=execution_id))
        if changed.rowcount != 1:
            return None
        execution = TaskExecution(
            execution_id=execution_id, account_id=account_id, task_code=code,
            trigger_type=trigger, status=S.PENDING, business_date=day, schedule_key=schedule_key,
            parent_execution_id=parent.execution_id if parent else None,
            retry_count=parent.retry_count + 1 if parent else 0, created_at=now,
        )
        self.session.add(execution)
        await self.session.flush()
        self.session.add(TaskOutbox(execution_id=execution_id, job_id=str(uuid4()),
                                    available_at=now + timedelta(seconds=delay)))
        await self.session.flush()
        return execution

    async def outbox(self, now, republish_seconds):
        rows = (await self.session.execute(select(TaskOutbox, TaskExecution).join(
            TaskExecution, TaskOutbox.execution_id == TaskExecution.execution_id,
        ).where(
            TaskExecution.status == S.PENDING, TaskOutbox.available_at <= now,
            or_(TaskOutbox.published_at.is_(None),
                TaskOutbox.published_at < now - timedelta(seconds=republish_seconds)),
        ).order_by(TaskOutbox.id).limit(100))).all()
        return [TaskJob(job_id=outbox.job_id, execution_id=execution.execution_id,
                        account_id=execution.account_id, task_code=execution.task_code,
                        trigger_type=execution.trigger_type, created_at=execution.created_at,
                        retry_count=execution.retry_count) for outbox, execution in rows]

    async def published(self, execution_id, now):
        await self.session.execute(update(TaskOutbox).where(
            TaskOutbox.execution_id == execution_id,
        ).values(published_at=now, attempt_count=TaskOutbox.attempt_count + 1))

    async def failures(self, day=None, account_id=None, before_id=None, retryable_codes=None, bounds=None):
        child = TaskExecution.__table__.alias("child")
        query = select(TaskExecution).where(TaskExecution.status == S.FAILED).where(
            ~select(child.c.id).where(child.c.parent_execution_id == TaskExecution.execution_id).exists(),
        )
        if day is not None:
            query = query.where(self.on_day(day, bounds))
        if account_id is not None:
            query = query.where(TaskExecution.account_id == account_id)
        if before_id is not None:
            query = query.where(TaskExecution.id < before_id)
        if retryable_codes is not None:
            query = query.where(TaskExecution.error_code.in_(retryable_codes), TaskExecution.dlq_at.is_(None))
        return list(await self.session.scalars(query.order_by(TaskExecution.id.desc()).limit(1000)))

    async def enabled(self, after_id=0):
        return list((await self.session.execute(select(
            TaskConfig.id, TaskConfig.account_id, TaskConfig.task_code,
        ).join(Account, Account.id == TaskConfig.account_id).join(
            TaskDefinition, TaskDefinition.task_code == TaskConfig.task_code,
        ).where(Account.status == "ACTIVE", Account.deleted_at.is_(None),
                TaskConfig.enabled.is_(True), TaskDefinition.status == "ACTIVE",
                TaskConfig.id > after_id).order_by(TaskConfig.id).limit(100))).all())

    async def expired(self, now, legacy_before):
        return list(await self.session.scalars(select(TaskExecution).where(
            TaskExecution.status == S.RUNNING,
            or_(TaskExecution.lease_until <= now,
                and_(TaskExecution.lease_until.is_(None), TaskExecution.start_time < legacy_before)),
        ).limit(100)))

    async def start(self, execution_id, worker_id, lease_token, now, ttl):
        changed = await self.session.execute(update(TaskExecution).where(
            TaskExecution.execution_id == execution_id, TaskExecution.status == S.PENDING,
        ).values(status=S.RUNNING, worker_id=worker_id, lease_token=lease_token,
                 lease_until=now + timedelta(seconds=ttl), heartbeat_at=now, start_time=now))
        return changed.rowcount == 1

    async def renew(self, execution_id, worker_id, lease_token, now, ttl):
        changed = await self.session.execute(update(TaskExecution).where(
            TaskExecution.execution_id == execution_id, TaskExecution.status == S.RUNNING,
            TaskExecution.worker_id == worker_id, TaskExecution.lease_token == lease_token,
            TaskExecution.lease_until > now,
        ).values(heartbeat_at=now, lease_until=now + timedelta(seconds=ttl)))
        return changed.rowcount == 1

    async def finish(self, execution, result, now, *, worker_id=None, lease_token=None, recovery=False):
        conditions = [TaskExecution.execution_id == execution.execution_id,
                      TaskExecution.status == execution.status]
        if recovery:
            conditions.append(or_(TaskExecution.lease_until <= now, TaskExecution.lease_until.is_(None)))
        elif execution.status == S.RUNNING:
            conditions.extend([TaskExecution.worker_id == worker_id,
                               TaskExecution.lease_token == lease_token, TaskExecution.lease_until > now])
        changed = await self.session.execute(update(TaskExecution).where(*conditions).values(
            status=result.status, end_time=now, result_json=result.model_dump(mode="json"),
            error_code=result.error_code, error_message=result.message if not result.success else None,
            lease_until=None,
        ))
        if changed.rowcount != 1:
            return False
        await self.session.execute(update(TaskConfig).where(
            TaskConfig.account_id == execution.account_id, TaskConfig.task_code == execution.task_code,
            TaskConfig.active_execution_id == execution.execution_id,
        ).values(active_execution_id=None))
        return True

    async def mark_dlq(self, execution_id, now):
        await self.session.execute(update(TaskExecution).where(
            TaskExecution.execution_id == execution_id,
        ).values(dlq_at=now))
