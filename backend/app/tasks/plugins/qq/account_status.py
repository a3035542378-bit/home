from typing import ClassVar

from app.adapters.onebot.exceptions import OneBotNotConnectedError
from app.tasks.errors import TaskPreconditionError
from app.tasks.plugins.qq.common import EmptyConfig, QQReadOnlyTask, adapter, result
from app.tasks.registry import register_task


@register_task
class QQAccountStatusTask(QQReadOnlyTask):
    task_code = "QQ_ACCOUNT_STATUS"
    task_name = "QQ 账号状态"
    config_schema = EmptyConfig
    timeout_seconds = 10
    required_capabilities: ClassVar[dict[str, set[str]]] = {"onebot": {"login_info", "status"}}

    async def execute(self, context):
        onebot = adapter(context)
        await onebot.health_check()
        login = await onebot.get_login_info()
        status = await onebot.get_status()
        if str(login.user_id) != context.account.account_no:
            raise TaskPreconditionError("ONEBOT_ACCOUNT_MISMATCH", "当前登录账号与任务账号不一致")
        if not status.online or not status.good:
            raise OneBotNotConnectedError()
        return result(
            context,
            {
                "account_id": context.account.id,
                "qq": "***" + str(login.user_id)[-4:],
                "nickname": login.nickname[:128],
                "online": status.online,
                "good": status.good,
                "connection_state": "CONNECTED",
            },
            "CONNECTED",
        )
