from types import MappingProxyType

from app.executors.models import ExecutorType as E
from app.executors.models import Operation, OperationCode, RiskLevel
from app.executors.models import VerificationLevel as V

# 按 Operation 明确登记顺序；不是对所有任务套用一份全局执行器优先级。
_READS = {
    "QQ_ACCOUNT_STATUS_READ": (E.ONEBOT, ("status", "login_info")),
    "QQ_FRIEND_SUMMARY_READ": (E.ONEBOT, ("friend_list",)),
    "QQ_GROUP_SUMMARY_READ": (E.ONEBOT, ("group_list",)),
    "QQ_RUNTIME_STATUS_READ": (E.ONEBOT, ("status",)),
    "QQ_WEB_LOGIN_STATUS_READ": (E.BROWSER, ("site.qq.login_status",)),
    "QQ_WEB_PAGE_STATUS_READ": (E.BROWSER, ("site.qq.page_status",)),
    "QQ_TASK_CENTER_READ": (E.BROWSER, ("site.qq.task_center.read",)),
    "QQ_ACTIVITY_READ": (E.BROWSER, ("site.qq.activity.read",)),
}
def _operations():
    result = {}
    for code in OperationCode:
        if code in _READS:
            executor, capabilities = _READS[code]
            result[code] = Operation(code, True, True, RiskLevel.SAFE_READONLY, "NONE",
                                     (executor, E.MOBILE), capabilities)
        else:
            result[code] = Operation(code, False, False, RiskLevel.HIGH_SIDE_EFFECT, "HIGH",
                                     (E.ONEBOT, E.BROWSER, E.MOBILE), implemented=False)
    return MappingProxyType(result)


OPERATIONS = _operations()

# 业务验证证据独立于 Browser 基础设施验证，不能通过请求/环境变量提升级别。
VERIFICATIONS = MappingProxyType({
    (OperationCode(code), executor): V.MOCK_ONLY if executor == E.ONEBOT else V.FIXTURE_VERIFIED
    for code, (executor, _) in _READS.items()
})
INFRASTRUCTURE = MappingProxyType({"browser.chromium": V.REAL_ENV_VERIFIED,
    "onebot.business": V.MOCK_ONLY, "qq_web.fixture": V.FIXTURE_VERIFIED,
    "qq_web.real": V.NOT_VERIFIED, "mobile.real": V.NOT_VERIFIED})
