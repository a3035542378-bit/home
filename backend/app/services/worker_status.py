from redis.exceptions import RedisError

from app.core.errors import BusinessError
from app.workers.heartbeat import list_workers


class WorkerStatusService:
    def __init__(self, redis, settings):
        self.redis, self.settings = redis, settings

    async def list(self):
        try:
            return await list_workers(self.redis, self.settings.worker_key_prefix)
        except RedisError as exc:
            raise BusinessError("REDIS_UNAVAILABLE", "暂时无法查询 Worker 状态", 503) from exc
