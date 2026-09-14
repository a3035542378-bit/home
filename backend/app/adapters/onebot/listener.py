import asyncio
import logging
import signal
from contextlib import suppress
from functools import partial

from app.adapters.onebot.events import EventBus
from app.adapters.onebot.websocket_client import OneBotWebSocketClient
from app.core.config import Settings
from app.core.database import Database
from app.core.logging import configure_logging
from app.services.onebot import OneBotService
from app.services.unit_of_work import UnitOfWork

logger = logging.getLogger("app.onebot.listener")


class LoginStatusHandler:
    def __init__(self, service, endpoint):
        self.service, self.endpoint = service, endpoint

    async def __call__(self, event):
        await self.service.event_status(self.endpoint, event)


class OneBotListener:
    def __init__(self, service, settings):
        self.service, self.settings = service, settings
        self.stop = asyncio.Event()
        self.nodes = {}

    async def _node(self, endpoint):
        bus = EventBus()
        bus.subscribe(LoginStatusHandler(self.service, endpoint))
        client = OneBotWebSocketClient(self.service.connection_settings(endpoint), bus,
                                       partial(self.service.ws_state, endpoint))
        consumer = asyncio.create_task(bus.run())
        receiver = asyncio.create_task(client.run())
        try:
            while not self.stop.is_set():
                if receiver.done():
                    await receiver
                    break
                try:
                    await self.service.ws_state(endpoint, client.state)
                    await self.service.health(endpoint.node_id)
                    logger.info("onebot_metrics", extra={"event": "onebot_metrics",
                                "node_id": endpoint.node_id, "status": client.state,
                                "onebot_events_total": bus.metrics["onebot_events_total"],
                                "onebot_ws_connected": client.metrics["onebot_ws_connected"],
                                "onebot_ws_reconnect_total": client.metrics["onebot_ws_reconnect_total"]})
                except Exception:  # noqa: BLE001 - 单节点探测失败不影响其他节点
                    logger.warning("onebot_poll_failed", extra={"event": "onebot_poll_failed", "node_id": endpoint.node_id})
                with suppress(TimeoutError):
                    await asyncio.wait_for(self.stop.wait(), self.settings.onebot_poll_interval)
        finally:
            # 先同步取消子任务，再等待清理，避免关闭 socket 期间二次取消遗留消费者。
            client.stop_event.set()
            receiver.cancel()
            consumer.cancel()
            await asyncio.gather(receiver, consumer, return_exceptions=True)

    async def sync(self):
        endpoints = {e.node_id: e for e in await self.service.endpoints()}
        for node_id, (old, task) in list(self.nodes.items()):
            if endpoints.get(node_id) != old or task.done():
                task.cancel()
                results = await asyncio.gather(task, return_exceptions=True)
                if any(isinstance(result, Exception) for result in results):
                    logger.warning("onebot_node_restarted", extra={"event": "onebot_node_restarted", "node_id": node_id})
                del self.nodes[node_id]
        for node_id, endpoint in endpoints.items():
            if node_id not in self.nodes:
                self.nodes[node_id] = (endpoint, asyncio.create_task(self._node(endpoint)))

    async def run(self):
        try:
            while not self.stop.is_set():
                try:
                    await self.sync()
                except Exception:  # noqa: BLE001 - 数据库恢复后自动重新读取节点
                    logger.warning("onebot_listener_sync_failed", extra={"event": "onebot_listener_sync_failed"})
                with suppress(TimeoutError):
                    await asyncio.wait_for(self.stop.wait(), self.settings.onebot_poll_interval)
        finally:
            for _, task in self.nodes.values():
                task.cancel()
            await asyncio.gather(*(task for _, task in self.nodes.values()), return_exceptions=True)


async def main():
    settings = Settings()
    configure_logging()
    database = Database(settings)
    service = OneBotService(UnitOfWork(database.sessions), settings)
    listener = OneBotListener(service, settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, listener.stop.set)
    try:
        await listener.run()
    finally:
        await service.aclose()
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
