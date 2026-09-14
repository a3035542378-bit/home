import asyncio
from uuid import uuid4

import pytest

from app.queue.base import TaskJob
from app.queue.lock import TaskLock
from app.queue.redis_stream import RedisTaskQueue


def job():
    return TaskJob(execution_id=str(uuid4()), account_id=1, task_code="MOCK_SUCCESS", trigger_type="MANUAL")


def test_job_serialization():
    original = job()
    assert TaskJob.model_validate_json(original.model_dump_json()) == original
    with pytest.raises(ValueError):
        TaskJob(execution_id="x", account_id=0, task_code="BAD", trigger_type="MANUAL")


async def test_stream_enqueue_ack(broker):
    redis, prefix = broker
    queue = RedisTaskQueue(redis, prefix, dlq=prefix + ":dlq")
    original = job()
    await queue.enqueue(original)
    assert await queue.size() == 1
    delivery = await queue.dequeue()
    assert TaskJob.model_validate_json(delivery.payload) == original
    assert (await redis.xpending(prefix, queue.group))["pending"] == 1
    await queue.ack(delivery)
    assert await queue.size() == 0


async def test_pending_reclaim_and_dlq(broker):
    redis, prefix = broker
    first = RedisTaskQueue(redis, prefix, consumer="first", dlq=prefix + ":dlq", reclaim_ms=0)
    second = RedisTaskQueue(redis, prefix, consumer="second", dlq=prefix + ":dlq", reclaim_ms=0)
    await first.enqueue(job())
    delivery = await first.dequeue()
    reclaimed = await second.dequeue()
    assert delivery.message_id == reclaimed.message_id
    await second.dead_letter(reclaimed, "RETRY_EXHAUSTED", "second")
    assert await redis.xlen(prefix + ":dlq") == 1
    assert await second.size() == 0
    await second.dead_letter(reclaimed, "RETRY_EXHAUSTED", "second")
    assert await redis.xlen(prefix + ":dlq") == 1


async def test_lock_expiry_and_token_protection(broker):
    redis, prefix = broker
    a = TaskLock(redis, prefix + ":lock", 0.02)
    b = TaskLock(redis, prefix + ":lock", 2)
    assert await a.acquire()
    assert not await b.acquire()
    await asyncio.sleep(0.04)
    assert await b.acquire()
    assert not await a.release()
    assert not await a.renew()
    assert await b.renew()
    assert await redis.pttl(b.key) > 0
    assert await b.release()


async def test_invalid_payload_dlq_is_redacted(broker):
    redis, prefix = broker
    queue = RedisTaskQueue(redis, prefix, dlq=prefix + ":dlq")
    await redis.xadd(prefix, {"job": '{"password":"secret-value"}'})
    delivery = await queue.dequeue()
    await queue.dead_letter(delivery, "INVALID_JOB", "test")
    records = await redis.xrange(queue.dlq)
    assert "secret-value" not in str(records)
