from app.adapters.sites.base import SiteAdapter
from app.adapters.sites.qq.exceptions import SiteNeedUserAction, SiteParseFailed
from app.adapters.sites.qq.schemas import (
    ActivitySummary,
    LoginState,
    LoginStatus,
    PageKey,
    PageStatus,
    SiteEvidence,
    TaskCenterSummary,
    TaskItem,
)
from app.adapters.sites.qq.web import CAPABILITIES
from app.models.common import utcnow


class FakeQQSiteAdapter(SiteAdapter):
    def __init__(self, mode="authenticated"):
        self.mode, self.calls = mode, []

    def capabilities(self):
        return dict(CAPABILITIES)

    def _read(self, method, key, count=0):
        self.calls.append(method)
        if self.mode == "parse_error":
            raise SiteParseFailed()
        state = {"need_login": LoginState.NOT_AUTHENTICATED,
                 "need_verification": LoginState.NEED_DEVICE_VERIFICATION}.get(self.mode)
        if state:
            raise SiteNeedUserAction(state)
        return SiteEvidence(page_key=key, final_url="https://fixture.invalid", page_title="QQ Web Fixture",
                            parsed_item_count=count, checked_at=utcnow().isoformat())

    async def check_login_status(self, page_key=PageKey.PROFILE):
        return LoginStatus(login_state=LoginState.AUTHENTICATED,
                           evidence=self._read("login", page_key))

    async def get_page_status(self, page_key=PageKey.PROFILE):
        return PageStatus(login_state=LoginState.AUTHENTICATED,
                          evidence=self._read("page", page_key))

    async def get_task_center_summary(self):
        evidence = self._read("tasks", PageKey.TASK_CENTER, 1)
        return TaskCenterSummary(total=1, completed=0, pending=1,
            items=[TaskItem(task_key="read", title="阅读状态", status="PENDING")], evidence=evidence)

    async def get_activity_summary(self):
        return ActivitySummary(activity_count=2, available_count=1,
                               evidence=self._read("activity", PageKey.ACTIVITY_CENTER, 2))
