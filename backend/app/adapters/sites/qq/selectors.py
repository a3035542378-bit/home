"""仅本地 Fixture 的规则；禁止作为真实 QQ Selector 使用。"""
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.adapters.sites.qq.exceptions import SiteNotConfigured
from app.adapters.sites.qq.schemas import PageKey

LOGIN = "[data-fixture-login]"
TASK_CONTAINER = "#fixture-task-center"
TASK_ITEMS = "#fixture-task-center [data-task-key]"
ACTIVITY_CONTAINER = "#fixture-activity"
ACTIVITY_ITEMS = "#fixture-activity [data-available]"
# 静态标题白名单，页面中任意文本都不能成为证据或摘要。
TITLES = {"read": "阅读状态", "visit": "访问状态", "reward": "可领取状态"}
PATHS = frozenset({
    "/qq/login-authenticated", "/qq/login-required", "/qq/device-verification",
    "/qq/qr", "/qq/captcha", "/qq/unknown", "/qq/task-center",
    "/qq/task-center-empty", "/qq/task-center-layout-broken", "/qq/task-center-parse-error",
    "/qq/activity", "/qq/activity-empty", "/qq/activity-parse-error", "/qq/redirect-blocked", "/qq/subrequest-blocked",
})


@dataclass(frozen=True)
class FixtureProfile:
    origin: str
    profile_path: str = "/qq/login-authenticated"
    task_path: str = "/qq/task-center"
    activity_path: str = "/qq/activity"

    def __post_init__(self):
        url = urlsplit(self.origin)
        if (url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port
                or url.username or url.password or url.path or url.query or url.fragment
                or any(path not in PATHS for path in (self.profile_path, self.task_path, self.activity_path))):
            raise SiteNotConfigured()

    def url(self, key):
        return self.origin + {PageKey.PROFILE: self.profile_path, PageKey.TASK_CENTER: self.task_path,
                              PageKey.ACTIVITY_CENTER: self.activity_path}[PageKey(key)]

    def permits(self, url, method="GET"):
        # 只允许显式注入的 loopback Fixture；不能由任务参数或环境变量启用。
        return method in {"GET", "HEAD"} and url in {self.origin + path for path in PATHS}
