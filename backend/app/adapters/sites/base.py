from abc import ABC, abstractmethod


class SiteAdapter(ABC):
    @abstractmethod
    def capabilities(self) -> dict[str, bool]: ...

    @abstractmethod
    async def check_login_status(self, page_key): ...

    @abstractmethod
    async def get_page_status(self, page_key): ...

    @abstractmethod
    async def get_task_center_summary(self): ...

    @abstractmethod
    async def get_activity_summary(self): ...
