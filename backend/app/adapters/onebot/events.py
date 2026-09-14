import asyncio
import json
import logging
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.adapters.onebot.schemas import OnlineStatus

logger = logging.getLogger("app.onebot.events")


class BaseOneBotEvent(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)
    time: int = 0
    self_id: int = Field(default=0, ge=0)
    post_type: str
    raw_event: dict[str, Any] = Field(default_factory=dict, repr=False, exclude=True)


class MetaEvent(BaseOneBotEvent):
    post_type: Literal["meta_event"]
    meta_event_type: str
    status: OnlineStatus | None = None


class MessageEvent(BaseOneBotEvent):
    post_type: Literal["message", "message_sent"]
    message_type: str
    message_id: int


class NoticeEvent(BaseOneBotEvent):
    post_type: Literal["notice"]
    notice_type: str


class RequestEvent(BaseOneBotEvent):
    post_type: Literal["request"]
    request_type: str


class UnknownEvent(BaseOneBotEvent):
    post_type: str = "unknown"


EVENT_TYPES = {"meta_event": MetaEvent, "message": MessageEvent, "message_sent": MessageEvent,
               "notice": NoticeEvent, "request": RequestEvent}


def parse_event(payload: str | bytes) -> BaseOneBotEvent:
    try:
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise TypeError()
        model = EVENT_TYPES.get(data.get("post_type"), UnknownEvent)
        return model.model_validate({**data, "raw_event": data})
    except (ValueError, TypeError, ValidationError):
        logger.warning("onebot_invalid_event", extra={"event": "onebot_invalid_event"})
        return UnknownEvent()


class EventBus:
    """有界队列提供背压，事件仅保留在内存；订阅者失败不影响其他订阅者。"""
    def __init__(self, maxsize=1000, handler_timeout=10):
        self.queue = asyncio.Queue(maxsize=maxsize)
        self.handlers = []
        self.handler_timeout = handler_timeout
        self.metrics = Counter()

    def subscribe(self, handler):
        self.handlers.append(handler)

    async def publish(self, event: BaseOneBotEvent):
        await self.queue.put(event)
        self.metrics["onebot_events_total"] += 1

    async def _dispatch(self, handler, event):
        try:
            async with asyncio.timeout(self.handler_timeout):
                await handler(event)
        except Exception:  # noqa: BLE001 - 订阅者隔离，禁止输出事件或异常原文
            self.metrics["handler_errors"] += 1
            logger.warning("onebot_handler_failed", extra={"event": "onebot_handler_failed"})

    async def run(self):
        while True:
            event = await self.queue.get()
            try:
                await asyncio.gather(*(self._dispatch(h, event) for h in self.handlers))
            finally:
                self.queue.task_done()
