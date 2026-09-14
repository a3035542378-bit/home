from app.adapters.errors import AdapterError
from app.adapters.sites.qq.schemas import LoginState


class SiteNotConfigured(AdapterError):
    code = "SITE_NOT_CONFIGURED"
    message = "站点 URL 或经过验证的页面规则尚未配置"


class SiteNeedUserAction(AdapterError):
    code = "SITE_NEED_USER_ACTION"
    message = "需要本人完成登录或验证"

    def __init__(self, state=LoginState.UNKNOWN):
        self.state = LoginState(state)
        super().__init__()


class SiteNotAuthenticated(SiteNeedUserAction):
    code = "SITE_NOT_AUTHENTICATED"

    def __init__(self):
        super().__init__(LoginState.NOT_AUTHENTICATED)


class SiteNavigationFailed(AdapterError):
    code = "SITE_NAVIGATION_FAILED"
    message = "站点导航暂时失败"
    retryable = True


class SiteLayoutChanged(AdapterError):
    code = "SITE_LAYOUT_CHANGED"
    message = "站点页面结构与已验证规则不一致"


class SiteParseFailed(AdapterError):
    code = "SITE_PARSE_FAILED"
    message = "站点摘要数据无法安全解析"
