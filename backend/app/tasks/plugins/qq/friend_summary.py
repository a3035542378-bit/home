from typing import ClassVar

from app.tasks.plugins.qq.common import FriendConfig, QQReadOnlyTask, adapter, measure, result
from app.tasks.registry import register_task


@register_task
class QQFriendSummaryTask(QQReadOnlyTask):
    task_code = "QQ_FRIEND_SUMMARY"
    task_name = "QQ 好友统计"
    config_schema = FriendConfig
    timeout_seconds = 15
    required_capabilities: ClassVar[dict[str, set[str]]] = {"onebot": {"friend_list"}}

    async def execute(self, context):
        onebot = adapter(context)
        with measure(context, "FRIEND_LIST"):
            friends = await onebot.get_friend_list()
        data = {"friend_count": len(friends)}
        if context.validated_config.include_category_counts:
            data.update(
                remark_count=sum(bool(f.remark.strip()) for f in friends),
                nickname_count=sum(bool(f.nickname.strip()) for f in friends),
            )
        del friends
        return result(context, data)
