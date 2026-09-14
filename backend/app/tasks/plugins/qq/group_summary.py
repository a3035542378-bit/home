from typing import ClassVar

from app.tasks.plugins.qq.common import GroupConfig, QQReadOnlyTask, adapter, measure, result
from app.tasks.registry import register_task


@register_task
class QQGroupSummaryTask(QQReadOnlyTask):
    task_code = "QQ_GROUP_SUMMARY"
    task_name = "QQ 群统计"
    config_schema = GroupConfig
    timeout_seconds = 15
    required_capabilities: ClassVar[dict[str, set[str]]] = {"onebot": {"group_list"}}

    async def execute(self, context):
        onebot = adapter(context)
        with measure(context, "GROUP_LIST"):
            groups = await onebot.get_group_list()
        data = {"group_count": len(groups)}
        del groups
        if context.validated_config.include_role_counts:
            # OneBot 标准群列表无可靠的当前账号角色字段，不做 N+1 详情查询。
            data.update(role_counts_supported=False, owned_group_count=None, admin_group_count=None)
        return result(context, data)
