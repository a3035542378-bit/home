import asyncio
import hashlib
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

from pydantic import SecretStr

from app.adapters.onebot import OneBotAdapter
from app.adapters.onebot.exceptions import (
    OneBotAuthenticationError,
    OneBotError,
)
from app.adapters.onebot.retry_scope import retry_scope
from app.adapters.registry import AdapterRegistry
from app.core.errors import BusinessError
from app.models.common import utcnow
from app.schemas.onebot import NodeHealth

logger = logging.getLogger("app.onebot.service")


@dataclass(frozen=True)
class Endpoint:
    node_id: int
    revision: int
    http_url: str | None
    ws_url: str | None
    secret_ref: str | None


class OneBotService:
    def __init__(self, uow, settings, adapter_factory=OneBotAdapter):
        self.uow, self.settings, self.adapter_factory = uow, settings, adapter_factory
        self.pool = {}
        self.pool_lock = asyncio.Lock()

    async def endpoints(self):
        async with self.uow.transaction() as repos:
            return [
                Endpoint(n.id, n.config_revision, n.onebot_http_url, n.onebot_ws_url, n.secret_ref)
                for n in await repos.nodes.onebot_nodes()
            ]

    async def endpoint(self, node_id):
        async with self.uow.transaction() as repos:
            node = await repos.nodes.get(node_id)
            if node is None:
                raise BusinessError("NODE_NOT_FOUND", "节点不存在", 404)
            if node.adapter_type != "ONEBOT":
                raise BusinessError("ADAPTER_TYPE_MISMATCH", "节点不是 OneBot 类型", 409)
            return Endpoint(
                node.id,
                node.config_revision,
                node.onebot_http_url,
                node.onebot_ws_url,
                node.secret_ref,
            )

    def connection_settings(self, endpoint):
        tokens = json.loads(self.settings.onebot_node_tokens.get_secret_value())
        if endpoint.secret_ref == "default":
            credential = self.settings.onebot_access_token.get_secret_value()
        elif endpoint.secret_ref:
            if endpoint.secret_ref not in tokens:
                raise BusinessError("NODE_SECRET_NOT_CONFIGURED", "节点凭据引用未配置", 503)
            credential = tokens[endpoint.secret_ref]
        else:
            credential = ""
        # 全局地址只允许通过 default 引用显式启用，不自动分配给所有账号。
        http_url, ws_url = endpoint.http_url, endpoint.ws_url
        if endpoint.secret_ref == "default":
            http_url = http_url or (
                self.settings.onebot_http_url.get_secret_value()
                if self.settings.onebot_http_url
                else None
            )
            ws_url = ws_url or (
                self.settings.onebot_ws_url.get_secret_value()
                if self.settings.onebot_ws_url
                else None
            )
        return self.settings.model_copy(
            update={
                "onebot_http_url": SecretStr(http_url) if http_url else None,
                "onebot_ws_url": SecretStr(ws_url) if ws_url else None,
                "onebot_access_token": SecretStr(credential),
            }
        )

    @asynccontextmanager
    async def adapter(self, endpoint):
        config = self.connection_settings(endpoint)
        fingerprint = hashlib.sha256(
            config.onebot_access_token.get_secret_value().encode()
        ).hexdigest()
        key = (endpoint, fingerprint)
        async with self.pool_lock:
            if key not in self.pool:
                self.pool[key] = [self.adapter_factory(config), 0]
            entry = self.pool[key]
            entry[1] += 1
        try:
            yield entry[0]
        finally:
            async with self.pool_lock:
                entry[1] -= 1
                for old_key, old_entry in list(self.pool.items()):
                    if (
                        old_key != key
                        and old_key[0].node_id == endpoint.node_id
                        and old_entry[1] == 0
                    ):
                        await old_entry[0].aclose()
                        del self.pool[old_key]

    async def aclose(self):
        for adapter, _ in self.pool.values():
            await adapter.aclose()
        self.pool.clear()

    @asynccontextmanager
    async def for_context(self, context, required):
        if "onebot" not in required:
            yield {}
            return
        if context.account.node_id is None:
            raise BusinessError("NODE_NOT_CONFIGURED", "账号未绑定节点")
        endpoint = await self.endpoint(context.account.node_id)
        with retry_scope(context.onebot_worker_retry):
            async with self.adapter(endpoint) as adapter:
                async with self.checked_adapter(context, required, adapter) as checked:
                    yield {"onebot": checked}

    @asynccontextmanager
    async def checked_adapter(self, context, required, adapter):
        AdapterRegistry({"onebot": adapter}).require({"onebot": required["onebot"]})
        if context.onebot_status_only:
            if required["onebot"] != {"status"}:
                raise BusinessError("CAPABILITY_UNSUPPORTED", "仅状态任务不得要求其他 OneBot 能力")
            yield StatusOnlyAdapter(adapter)
            return
        login = await adapter.get_login_info()
        if context.account.platform != "QQ" or str(login.user_id) != context.account.account_no:
            raise BusinessError("ONEBOT_IDENTITY_MISMATCH", "节点登录身份与任务账号不匹配")
        yield adapter

    async def configure(self, node_id, data):
        async with self.uow.transaction() as repos:
            node = await repos.nodes.locked(node_id)
            if not node:
                raise BusinessError("NODE_NOT_FOUND", "节点不存在", 404)
            if node.adapter_type != "ONEBOT":
                raise BusinessError("ADAPTER_TYPE_MISMATCH", "节点不是 OneBot 类型", 409)
            for key, value in data.model_dump().items():
                setattr(node, key, value)
            node.config_revision += 1
            node.status, node.ws_state = "UNKNOWN", "UNKNOWN"
            node.ws_seen_at, node.checked_at = None, None
            for account in await repos.accounts.for_node(node_id):
                account.online_status = "UNKNOWN"

    async def ws_state(self, endpoint, state):
        async with self.uow.transaction() as repos:
            node = await repos.nodes.locked(endpoint.node_id)
            if node and node.config_revision == endpoint.revision:
                node.ws_state, node.ws_seen_at = state, utcnow()

    async def event_status(self, endpoint, event):
        from app.adapters.onebot.events import MetaEvent

        if (
            not isinstance(event, MetaEvent)
            or event.meta_event_type != "heartbeat"
            or not event.self_id
        ):
            return
        status = event.status
        if status is None:
            return
        async with self.uow.transaction() as repos:
            node = await repos.nodes.locked(endpoint.node_id)
            if not node or node.config_revision != endpoint.revision:
                return
            for account in await repos.accounts.for_node(endpoint.node_id):
                account.online_status = (
                    ("ONLINE" if status.online and status.good else "OFFLINE")
                    if account.platform == "QQ" and account.account_no == str(event.self_id)
                    else "UNKNOWN"
                )

    async def health(self, node_id):
        endpoint = await self.endpoint(node_id)
        login, version, error, metrics = None, None, None, {}
        http_ok, online = False, False
        try:
            async with self.adapter(endpoint) as adapter:
                try:
                    status = await adapter.get_status()
                    online = status.online and status.good
                    http_ok = True
                    if online:
                        login = await adapter.get_login_info()
                        version = await adapter.get_version_info()
                finally:
                    metrics = dict(adapter.metrics)
        except (OneBotError, BusinessError) as exc:
            error = exc.code
            logger.warning(
                "onebot_probe_failed",
                extra={"event": "onebot_probe_failed", "node_id": node_id, "status": error},
            )
        now = utcnow()
        async with self.uow.transaction() as repos:
            node = await repos.nodes.locked(node_id)
            if node.config_revision != endpoint.revision:
                raise BusinessError("NODE_CONFIGURATION_CHANGED", "节点配置已变更，请重新查询", 409)
            accounts = await repos.accounts.for_node(node_id)
            fresh = node.ws_seen_at is not None and node.ws_seen_at > now - timedelta(
                seconds=self.settings.onebot_poll_interval * 3
            )
            ws = node.ws_state if fresh else "UNKNOWN"
            state = (
                "CONNECTED"
                if http_ok and online and ws == "CONNECTED"
                else "DEGRADED"
                if http_ok
                else "DISCONNECTED"
            )
            if error and state == "CONNECTED":
                state = "DEGRADED"
            if error == OneBotAuthenticationError.code or ws == "AUTH_FAILED":
                state = "AUTH_FAILED"
            for account in accounts:
                matches = (
                    login and account.platform == "QQ" and account.account_no == str(login.user_id)
                )
                account.online_status = (
                    "ONLINE" if matches else "OFFLINE" if http_ok and not online else "UNKNOWN"
                )
                if login and not matches:
                    state, error = "DEGRADED", "ONEBOT_IDENTITY_MISMATCH"
            node.status, node.checked_at = state, now
            ids = [account.id for account in accounts]
            return NodeHealth(
                node_id=node_id,
                adapter_type="ONEBOT",
                connection_state=state,
                account_id=ids[0] if len(ids) == 1 else None,
                account_ids=ids,
                login_info=login,
                version=version,
                error_code=error,
                checked_at=now,
                metrics=metrics,
            )

    async def summary(self):
        async with self.uow.transaction() as repos:
            nodes = await repos.nodes.onebot_nodes()
            cutoff = utcnow() - timedelta(seconds=self.settings.onebot_poll_interval * 3)
            return {
                str(n.id): n.status if n.checked_at and n.checked_at > cutoff else "UNKNOWN"
                for n in nodes
            }


class StatusOnlyAdapter:
    """仅暴露当前 Node 的在线布尔值，不允许状态任务读取其他身份数据。"""

    def __init__(self, adapter):
        self._adapter = adapter

    def capabilities(self):
        return {"status": True}

    async def get_status(self):
        return await self._adapter.get_status()
