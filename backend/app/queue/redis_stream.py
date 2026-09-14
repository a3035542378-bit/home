import hashlib
import json

from redis.exceptions import ResponseError

from app.models.common import utcnow
from app.queue.base import Delivery, TaskJob


class RedisTaskQueue:
    def __init__(self, redis, stream="qq:task:stream", group="qq-workers", consumer="dispatcher",
                 dlq="qq:task:dlq", reclaim_ms=60000):
        self.redis, self.stream, self.group = redis, stream, group
        self.consumer, self.dlq, self.reclaim_ms = consumer, dlq, reclaim_ms
        self.cursor = "0-0"

    async def ensure_group(self):
        try:
            await self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def enqueue(self, job: TaskJob) -> str:
        return await self.redis.xadd(self.stream, {"job": job.model_dump_json()})

    async def dequeue(self) -> Delivery | None:
        await self.ensure_group()
        claimed = await self.redis.xautoclaim(
            self.stream, self.group, self.consumer, self.reclaim_ms, self.cursor, count=1,
        )
        self.cursor = claimed[0]
        entries = claimed[1]
        if not entries:
            result = await self.redis.xreadgroup(
                self.group, self.consumer, {self.stream: ">"}, count=1, block=200,
            )
            entries = result[0][1] if result else []
        if not entries:
            return None
        message_id, fields = entries[0]
        return Delivery(message_id, fields.get("job", ""))

    async def ack(self, delivery: Delivery) -> None:
        # 本 Stream 专供一个消费者组；结果提交后才能 ACK 并清理消息。
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.xack(self.stream, self.group, delivery.message_id)
            pipe.xdel(self.stream, delivery.message_id)
            await pipe.execute()

    async def retry(self, job: TaskJob) -> str:
        # 传输层补投保留 execution_id；业务重试由 Service 创建新 execution。
        return await self.enqueue(job)

    async def size(self) -> int:
        return await self.redis.xlen(self.stream)

    async def dead_letter(self, delivery: Delivery, error_code: str, worker_id: str):
        try:
            original = TaskJob.model_validate_json(delivery.payload).model_dump(mode="json")
        except ValueError:
            # 畸形载荷可能包含凭据，仅保存摘要，不把未知原文写入 DLQ。
            original = {"sha256": hashlib.sha256(delivery.payload.encode()).hexdigest()}
        record = json.dumps({"job": original, "error_code": error_code,
                             "worker_id": worker_id, "time": utcnow().isoformat()})
        identity = error_code + ":" + str(original.get("execution_id", original.get("sha256")))
        await self.redis.eval("""
            if redis.call('XACK', KEYS[1], ARGV[1], ARGV[2]) == 1 then
                if redis.call('HSETNX', KEYS[3], ARGV[4], '1') == 1 then
                    redis.call('XADD', KEYS[2], '*', 'record', ARGV[3])
                end
                redis.call('XDEL', KEYS[1], ARGV[2])
                return 1
            end
            return 0
        """, 3, self.stream, self.dlq, self.dlq + ":index", self.group,
            delivery.message_id, record, identity)
