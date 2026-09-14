import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import Settings
from app.core.errors import BusinessError
from app.queue.base import TaskJob
from app.queue.redis_stream import RedisTaskQueue
from app.services.worker_status import WorkerStatusService


async def test_real_redis_unavailable(unused_tcp_port):
    client = Redis(host="127.0.0.1", port=unused_tcp_port, socket_connect_timeout=0.1,
                   decode_responses=True)
    try:
        queue = RedisTaskQueue(client)
        with pytest.raises(RedisConnectionError):
            await queue.enqueue(TaskJob(execution_id="test", account_id=1, task_code="MOCK_SUCCESS",
                                        trigger_type="MANUAL"))
        status = WorkerStatusService(client, Settings(_env_file=None,
                                     database_url="sqlite+aiosqlite:///:memory:"))
        with pytest.raises(BusinessError) as caught:
            await status.list()
        assert caught.value.code == "REDIS_UNAVAILABLE"
    finally:
        await client.aclose()
