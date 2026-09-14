from app.executors.models import RiskLevel


class RiskPolicy:
    def allows_selection(self, operation):
        # 本阶段只放行已验证的安全只读能力；指定执行器也不能开启写操作。
        return operation.read_only and operation.idempotent and operation.risk_level == RiskLevel.SAFE_READONLY

    def allows_fallback(self, operation):
        return self.allows_selection(operation)
