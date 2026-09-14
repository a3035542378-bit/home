from app.executors.errors import ERRORS, ExecutorRoutingError
from app.executors.models import CapabilityResolution, ExecutorType, RoutingMode
from app.executors.models import CapabilityStatus as S
from app.executors.resolver import CapabilityResolver


class ExecutorRouter:
    def __init__(self, resolver=None, *, priorities=None):
        self.resolver = resolver or CapabilityResolver()
        self.priorities = {}
        for code, values in (priorities or {}).items():
            spec = self.resolver.operation(code)
            try:
                values = tuple(ExecutorType(value) for value in values)
            except ValueError:
                raise ExecutorRoutingError() from None
            if not values or len(values) != len(set(values)) or not set(values) <= set(spec.allowed_executors):
                raise ExecutorRoutingError()
            self.priorities[spec.code] = values

    async def resolve(self, operation, context, *, mode=RoutingMode.PRODUCTION, preferred_executor=None):
        try:
            mode = RoutingMode(mode)
        except ValueError:
            raise ExecutorRoutingError("OPERATION_UNSUPPORTED") from None
        spec = self.resolver.operation(operation)
        candidates = (await self.resolver.resolve(operation, context, mode=mode)).candidates
        order = self.priorities.get(spec.code, spec.allowed_executors)
        order = (*order, *(value for value in spec.allowed_executors if value not in order))
        if preferred_executor is not None:
            try:
                preferred = ExecutorType(preferred_executor)
            except ValueError:
                raise ExecutorRoutingError("OPERATION_UNSUPPORTED") from None
            if preferred not in spec.allowed_executors:
                raise ExecutorRoutingError("OPERATION_UNSUPPORTED")
            # 明确选择不自动退回其他执行器。
            order = (preferred,)
        by_executor = {candidate.executor: candidate for candidate in candidates}
        challenge = next((c for c in candidates if c.status in {S.NEED_USER_ACTION, S.NOT_AUTHENTICATED}
                          or c.runtime_status in {S.NEED_USER_ACTION, S.NOT_AUTHENTICATED}), None)
        chosen = None if challenge else next((by_executor[e] for e in order
                                              if by_executor[e].status == S.AVAILABLE), None)
        first = challenge or chosen or by_executor[order[0]]
        return CapabilityResolution(operation=spec.code, selected_executor=chosen.executor if chosen else None,
            risk_level=spec.risk_level, status=first.status, reason=first.reason, mode=mode,
            error_code=None if chosen else ERRORS.get(first.status, "EXECUTOR_NOT_AVAILABLE"), candidates=candidates)

    async def require(self, operation, context, **options):
        result = await self.resolve(operation, context, **options)
        if result.selected_executor is None:
            raise ExecutorRoutingError(result.error_code)
        return result.selected_executor

    async def resolve_fallback(self, operation, context, *, failed_executor, failure_status, enabled=False):
        spec = self.resolver.operation(operation)
        if (not enabled or not self.resolver.policy.allows_fallback(spec)
                or failure_status not in {S.DEGRADED, S.SUPPORTED_NOT_READY}):
            raise ExecutorRoutingError("EXECUTOR_NEED_USER_ACTION" if failure_status in {
                S.NEED_USER_ACTION, S.NOT_AUTHENTICATED} else "EXECUTOR_NOT_AVAILABLE")
        try:
            failed_executor = ExecutorType(failed_executor)
        except ValueError:
            raise ExecutorRoutingError("OPERATION_UNSUPPORTED") from None
        if failed_executor not in spec.allowed_executors:
            raise ExecutorRoutingError("OPERATION_UNSUPPORTED")
        result = await self.resolve(operation, context)
        if any(c.runtime_status in {S.NEED_USER_ACTION, S.NOT_AUTHENTICATED} for c in result.candidates):
            raise ExecutorRoutingError("EXECUTOR_NEED_USER_ACTION")
        priorities = self.priorities.get(spec.code, spec.allowed_executors)
        order = (*priorities, *(e for e in spec.allowed_executors if e not in priorities))
        for executor in order:
            if executor != failed_executor:
                candidate = next(c for c in result.candidates if c.executor == executor)
                if candidate.status == S.AVAILABLE:
                    return await self.resolve(operation, context, preferred_executor=executor)
        raise ExecutorRoutingError()
