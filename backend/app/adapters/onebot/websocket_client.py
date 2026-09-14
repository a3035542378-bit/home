import asyncio
import logging
from collections import Counter
from time import monotonic

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from app.adapters.onebot.events import MetaEvent, parse_event

logger = logging.getLogger("app.onebot.ws")


class OneBotWebSocketClient:
    def __init__(self, settings, bus, on_state=None, *, connector=connect):
        self.settings, self.bus, self.on_state = settings, bus, on_state
        self.connector = connector
        self.metrics = Counter()
        self.connected = False
        self.state = "UNKNOWN"
        self.stop_event = asyncio.Event()
        self.socket = None
        self.backoff = settings.onebot_ws_reconnect_min_seconds

    async def _state(self, state):
        self.state = state
        self.connected = state == "CONNECTED"
        self.metrics["onebot_ws_connected"] = int(self.connected)
        if self.on_state:
            await self.on_state(state)

    async def stop(self):
        self.stop_event.set()
        if self.socket:
            await self.socket.close()

    async def run(self):
        config = self.settings
        if config.onebot_ws_url is None:
            await self._state("DISCONNECTED")
            await self.stop_event.wait()
            return
        credential = config.onebot_access_token.get_secret_value()
        while not self.stop_event.is_set():
            started = monotonic()
            last_heartbeat = started
            stable = False
            try:
                async with self.connector(
                    config.onebot_ws_url.get_secret_value(),
                    additional_headers={"Authorization": "Bearer " + credential} if credential else {},
                    proxy=None, open_timeout=config.onebot_connect_timeout,
                    close_timeout=2, ping_interval=20, ping_timeout=20,
                    max_size=1024 * 1024,
                ) as socket:
                    self.socket = socket
                    await self._state("CONNECTED")
                    while not self.stop_event.is_set():
                        remaining = config.onebot_ws_heartbeat_timeout - (monotonic() - last_heartbeat)
                        async with asyncio.timeout(max(0, remaining)):
                            payload = await socket.recv()
                        event = parse_event(payload)
                        if isinstance(event, MetaEvent) and event.meta_event_type == "heartbeat":
                            last_heartbeat = monotonic()
                            stable = last_heartbeat - started >= config.onebot_ws_heartbeat_timeout
                        await self.bus.publish(event)
            except asyncio.CancelledError:
                raise
            except InvalidStatus as exc:
                await self._state("AUTH_FAILED" if exc.response.status_code in {401, 403} else "DISCONNECTED")
            except Exception:  # noqa: BLE001 - 网络进程边界，仅记录固定事件
                await self._state("DISCONNECTED")
                logger.warning("onebot_ws_disconnected", extra={"event": "onebot_ws_disconnected"})
            finally:
                self.socket = None
                self.connected = False
                self.metrics["onebot_ws_connected"] = 0
            if self.stop_event.is_set():
                break
            # 长连接稳定一个心跳窗口后才重置，避免快速断开形成重连风暴。
            if stable:
                self.backoff = config.onebot_ws_reconnect_min_seconds
            self.metrics["onebot_ws_reconnect_total"] += 1
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.backoff)
            except TimeoutError:
                self.backoff = min(self.backoff * 2, config.onebot_ws_reconnect_max_seconds)
        await self._state("DISCONNECTED")
