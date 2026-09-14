from abc import ABC, abstractmethod

from app.adapters.errors import AdapterError


class MobileNotConfigured(AdapterError):
    code = "EXECUTOR_NOT_CONFIGURED"
    message = "真实 Mobile 执行器尚未配置"


class MobileAdapter(ABC):
    @abstractmethod
    def capabilities(self) -> dict[str, bool]: ...

    @abstractmethod
    async def health_check(self) -> bool: ...

    @abstractmethod
    async def read_page(self) -> dict: ...


class UnconfiguredMobileAdapter(MobileAdapter):
    def capabilities(self):
        return {key: False for key in ("mobile.available", "mobile.app.launch", "mobile.page.read")}

    async def health_check(self):
        return False

    async def read_page(self):
        raise MobileNotConfigured()


class FakeMobileAdapter(MobileAdapter):
    """只返回固定测试数据，不启动 App 或接入设备。"""
    def capabilities(self):
        return {"mobile.available": True, "mobile.page.read": True, "mobile.app.launch": False}

    async def health_check(self):
        return True

    async def read_page(self):
        return {"fixture": True, "item_count": 0}
