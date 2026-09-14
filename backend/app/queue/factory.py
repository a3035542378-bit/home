from app.queue.redis_stream import RedisTaskQueue


def make_queue(redis, settings, consumer="dispatcher"):
    return RedisTaskQueue(redis, settings.task_stream_name, settings.task_consumer_group, consumer,
                          settings.task_dlq_name, int(settings.execution_lease_seconds * 1000))
