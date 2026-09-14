from uuid import uuid4


class TaskLock:
    def __init__(self, redis, key: str, ttl_seconds: float):
        self.redis, self.key = redis, key
        self.ttl_ms = int(ttl_seconds * 1000)
        if self.ttl_ms < 1:
            raise ValueError("锁 TTL 必须大于 0")
        self.token = str(uuid4())

    async def acquire(self) -> bool:
        return bool(await self.redis.set(self.key, self.token, nx=True, px=self.ttl_ms))

    async def renew(self) -> bool:
        return bool(await self.redis.eval("""
            if redis.call('GET', KEYS[1]) == ARGV[1] then
                return redis.call('PEXPIRE', KEYS[1], ARGV[2])
            end
            return 0
        """, 1, self.key, self.token, self.ttl_ms))

    async def release(self) -> bool:
        return bool(await self.redis.eval("""
            if redis.call('GET', KEYS[1]) == ARGV[1] then
                return redis.call('DEL', KEYS[1])
            end
            return 0
        """, 1, self.key, self.token))
