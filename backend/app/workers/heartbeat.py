import json

from app.models.common import utcnow


class WorkerHeartbeat:
    def __init__(self, redis, worker_id, settings, clock=utcnow, browser_health=None):
        self.redis, self.worker_id, self.settings, self.clock = redis, worker_id, settings, clock
        self.browser_health = browser_health
        self.started_at = clock().isoformat()

    async def update(self, active, status="ONLINE"):
        await self.redis.set(self.settings.worker_key_prefix + self.worker_id, json.dumps({
            "worker_id": self.worker_id, "status": status, "started_at": self.started_at,
            "last_heartbeat": self.clock().isoformat(), "active_execution": sorted(active),
            "browser": self.browser_health() if self.browser_health and status == "ONLINE" else "DOWN",
        }), ex=self.settings.worker_heartbeat_ttl)


async def list_workers(redis, prefix):
    workers = []
    async for key in redis.scan_iter(match=prefix + "*"):
        raw = await redis.get(key)
        if raw:
            workers.append(json.loads(raw))
    return sorted(workers, key=lambda item: item["worker_id"])
