from app.adapters.errors import AdapterError


class BrowserError(AdapterError):
    code = "BROWSER_ERROR"
    message = "浏览器操作失败"
    retryable = False
    def __init__(self):
        self.error_code = self.code
        super().__init__()


class BrowserStartError(BrowserError):
    code = "BROWSER_START_ERROR"
    message = "浏览器启动失败"


class BrowserClosedError(BrowserError):
    code = "BROWSER_CLOSED"
    message = "浏览器已关闭或连接中断"


class BrowserSessionError(BrowserError):
    code = "BROWSER_SESSION_ERROR"
    message = "浏览器账号上下文操作失败"


class BrowserNavigationError(BrowserError):
    code = "BROWSER_NAVIGATION_ERROR"
    message = "页面导航失败"


class BrowserActionError(BrowserError):
    code = "BROWSER_ACTION_ERROR"
    message = "页面操作失败"


class BrowserTimeoutError(BrowserError):
    code = "BROWSER_TIMEOUT"
    message = "浏览器操作超时"


class BrowserNavigationTimeout(BrowserTimeoutError):
    code = "BROWSER_NAVIGATION_TIMEOUT"


class BrowserActionTimeout(BrowserTimeoutError):
    code = "BROWSER_ACTION_TIMEOUT"


class BrowserSelectorTimeout(BrowserTimeoutError):
    code = "BROWSER_SELECTOR_TIMEOUT"


class BrowserStorageError(BrowserError):
    code = "BROWSER_STORAGE_ERROR"
    message = "浏览器状态无法安全读取或保存"


class BrowserPageCrashError(BrowserError):
    code = "BROWSER_PAGE_CRASH"
    message = "浏览器页面已崩溃"


class BrowserUserActionRequired(BrowserError):
    code = "BROWSER_USER_ACTION_REQUIRED"
    message = "需要本人完成登录或验证后继续"
