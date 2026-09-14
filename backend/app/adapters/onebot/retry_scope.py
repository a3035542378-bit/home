"""按协程隔离重试所有权，避免共享连接池的任务互相改变预算。"""
from contextlib import contextmanager
from contextvars import ContextVar

worker_owns_retry = ContextVar("onebot_worker_owns_retry", default=False)


@contextmanager
def retry_scope(enabled):
    reset = worker_owns_retry.set(enabled)
    try:
        yield
    finally:
        worker_owns_retry.reset(reset)
