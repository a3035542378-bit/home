from app.core.errors import BusinessError
from app.executors.models import CapabilityStatus as S

ERRORS = {
    S.NOT_VERIFIED: "EXECUTOR_NOT_VERIFIED",
    S.NOT_CONFIGURED: "EXECUTOR_NOT_CONFIGURED",
    S.NOT_AUTHENTICATED: "EXECUTOR_NEED_USER_ACTION",
    S.NEED_USER_ACTION: "EXECUTOR_NEED_USER_ACTION",
    S.UNSUPPORTED: "OPERATION_UNSUPPORTED",
}


class ExecutorRoutingError(BusinessError):
    def __init__(self, code="EXECUTOR_NOT_AVAILABLE"):
        super().__init__(code, "当前 Operation 没有满足验证、运行状态和风险策略的执行器", 409)
