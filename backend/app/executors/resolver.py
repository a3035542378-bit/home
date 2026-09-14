from app.executors.catalog import OPERATIONS, VERIFICATIONS
from app.executors.errors import ERRORS, ExecutorRoutingError
from app.executors.models import (
    Candidate,
    CapabilityResolution,
    ExecutorRuntime,
    ExecutorType,
    OperationCode,
    RoutingMode,
)
from app.executors.models import CapabilityStatus as S
from app.executors.models import VerificationLevel as V
from app.executors.policy import RiskPolicy


class CapabilityResolver:
    def __init__(self, *, operations=OPERATIONS, verifications=VERIFICATIONS, policy=None):
        # 注入仅用于内部可信构造/测试，没有对外覆盖验证证据的 API。
        self.operations, self.verifications = operations, verifications
        self.policy = policy or RiskPolicy()

    def operation(self, code):
        try:
            return self.operations[OperationCode(code)]
        except (ValueError, KeyError):
            raise ExecutorRoutingError("OPERATION_UNSUPPORTED") from None

    @staticmethod
    def runtime_status(operation, executor, runtime):
        if not runtime.configured:
            return S.NOT_CONFIGURED
        if runtime.need_user_action:
            return S.NEED_USER_ACTION
        if not set(operation.capabilities).issubset(runtime.capabilities):
            return S.UNSUPPORTED
        if runtime.degraded:
            return S.DEGRADED
        if executor == ExecutorType.BROWSER:
            if not runtime.site_configured or (runtime.site_operations is not None
                                               and operation.code not in runtime.site_operations):
                return S.NOT_CONFIGURED
            if not runtime.state_present:
                return S.NOT_AUTHENTICATED
        if runtime.authenticated is False:
            return S.NOT_AUTHENTICATED
        if not runtime.ready or runtime.authenticated is not True:
            return S.SUPPORTED_NOT_READY
        return S.AVAILABLE

    async def resolve(self, operation, context, *, mode=RoutingMode.PRODUCTION):
        spec = self.operation(operation)
        candidates = []
        for executor in spec.allowed_executors:
            runtime = context.runtime.get(executor, ExecutorRuntime())
            level = self.verifications.get((spec.code, executor), V.NOT_VERIFIED)
            status = self.runtime_status(spec, executor, runtime)
            reason = status.value
            runtime_status = status
            if context.platform != "QQ":
                status, reason = S.UNSUPPORTED, "ACCOUNT_PLATFORM_UNSUPPORTED"
            elif not context.active:
                status, reason = S.SUPPORTED_NOT_READY, "ACCOUNT_DISABLED"
            elif runtime.need_user_action:
                status, reason = S.NEED_USER_ACTION, "USER_ACTION_REQUIRED"
            elif executor == ExecutorType.MOBILE and not runtime.configured:
                status, reason = S.NOT_CONFIGURED, "MOBILE_NOT_CONFIGURED"
            elif not spec.implemented:
                status, reason = S.NOT_VERIFIED, "OPERATION_NOT_IMPLEMENTED"
            elif level != V.REAL_ENV_VERIFIED:
                status, reason = S.NOT_VERIFIED, "REAL_BUSINESS_NOT_VERIFIED"
            elif not self.policy.allows_selection(spec):
                status, reason = S.SUPPORTED_NOT_READY, "RISK_POLICY_BLOCKED"
            candidates.append(Candidate(executor=executor, status=status, runtime_status=runtime_status,
                                        verification_level=level, reason=reason))
        first = next((candidate for candidate in candidates if candidate.status == S.NEED_USER_ACTION), candidates[0])
        return CapabilityResolution(operation=spec.code, risk_level=spec.risk_level, status=first.status,
            mode=mode, reason=first.reason, candidates=candidates,
            error_code=None if first.status == S.AVAILABLE else ERRORS.get(first.status, "EXECUTOR_NOT_AVAILABLE"))
