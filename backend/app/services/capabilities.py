from datetime import timedelta

from app.adapters.browser.exceptions import BrowserStorageError
from app.adapters.browser.storage import EncryptedFileStorage
from app.adapters.onebot.capability import CAPABILITIES as ONEBOT_CAPABILITIES
from app.adapters.sites.qq.web import CAPABILITIES as SITE_CAPABILITIES
from app.core.errors import BusinessError
from app.executors.models import ExecutorRuntime, ExecutorType, RoutingContext, RoutingMode
from app.executors.router import ExecutorRouter
from app.models.common import utcnow


class CapabilityService:
    """仅读取本地状态证据；能力查询不登录、不导航、不探测第三方。"""
    def __init__(self, uow, settings, *, workers=None, browser_health=None, storage=None, router=None):
        self.uow, self.settings, self.workers, self.browser_health = uow, settings, workers, browser_health
        self.storage = storage or EncryptedFileStorage(settings.browser_state_dir, settings.browser_storage_key)
        self.router = router or ExecutorRouter(priorities=settings.executor_priorities)

    async def context(self, account_id):
        now = utcnow()
        async with self.uow.transaction() as repos:
            account = await repos.accounts.get(account_id)
            if account is None:
                raise BusinessError("ACCOUNT_NOT_FOUND", "账号不存在", 404)
            node = await repos.nodes.get(account.node_id) if account.node_id else None
            configured = bool(node and node.adapter_type == "ONEBOT" and node.onebot_http_url)
            fresh = bool(node and node.checked_at and node.checked_at > now - timedelta(
                seconds=self.settings.onebot_poll_interval * 3))
            onebot = ExecutorRuntime(configured=configured, ready=bool(fresh and node.status == "CONNECTED"),
                authenticated=account.online_status == "ONLINE" if fresh else None,
                need_user_action=bool(node and node.status == "AUTH_FAILED"),
                degraded=bool(configured and (not fresh or node.status not in {"CONNECTED", "AUTH_FAILED"})),
                capabilities=frozenset(key for key, supported in ONEBOT_CAPABILITIES.items() if supported))
            platform, active = account.platform, account.status == "ACTIVE"
        browser_ready = self.browser_health is not None and self.browser_health() == "UP"
        degraded = False
        if self.workers is not None:
            try:
                workers = await self.workers.list()
                browser_ready = any(worker.get("status") == "ONLINE" and worker.get("browser") == "UP"
                                    for worker in workers)
            except BusinessError:
                degraded = True
        try:
            state = await self.storage.load(account_id)
            present = bool(state and (state.get("cookies") or state.get("origins")))
            del state
        except BrowserStorageError:
            present = False
        # State 存在不是登录成功；未进行页面核验时 authenticated 仍为未知。
        configured_operations = frozenset(code for code, value in {
            "QQ_WEB_LOGIN_STATUS_READ": self.settings.qq_web_base_url,
            "QQ_WEB_PAGE_STATUS_READ": self.settings.qq_web_base_url,
            "QQ_TASK_CENTER_READ": self.settings.qq_task_center_url,
            "QQ_ACTIVITY_READ": self.settings.qq_activity_url,
        }.items() if value)
        browser = ExecutorRuntime(configured=True, ready=browser_ready, authenticated=None,
            state_present=present, site_configured=bool(configured_operations), degraded=degraded,
            site_operations=configured_operations, capabilities=frozenset(SITE_CAPABILITIES))
        return RoutingContext(account_id, platform, active,
                              {ExecutorType.ONEBOT: onebot, ExecutorType.BROWSER: browser})

    async def list(self, account_id, mode=RoutingMode.PRODUCTION):
        context = await self.context(account_id)
        return [await self.router.resolve(operation, context, mode=mode)
                for operation in self.router.resolver.operations]


class BoundExecutorRouter:
    """供 TaskContext 使用的账号绑定入口，不能查询其他账号或提交自造运行证据。"""
    def __init__(self, service, account_id):
        self.service, self.account_id = service, account_id

    async def resolve(self, operation, context, **options):
        if context.account.id != self.account_id:
            raise BusinessError("EXECUTOR_NOT_AVAILABLE", "执行器上下文账号不匹配")
        runtime = await self.service.context(self.account_id)
        return await self.service.router.resolve(operation, runtime, **options)
