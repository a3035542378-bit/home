from typing import Protocol

from app.core.errors import BusinessError


class Adapter(Protocol):
    def capabilities(self) -> dict[str, bool]: ...
    async def aclose(self) -> None: ...


class AdapterRegistry:
    def __init__(self, adapters=None):
        self.adapters = dict(adapters or {})

    def get(self, name: str) -> Adapter:
        if name not in self.adapters:
            raise BusinessError("ADAPTER_NOT_CONFIGURED", "任务所需 Adapter 未配置")
        return self.adapters[name]

    def require(self, requirements: dict[str, set[str]]):
        for name, capabilities in requirements.items():
            adapter = self.get(name)
            available = adapter.capabilities()
            if any(not available.get(capability, False) for capability in capabilities):
                raise BusinessError("CAPABILITY_UNSUPPORTED", "Adapter 不支持任务所需能力")
