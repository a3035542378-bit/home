from app.adapters.errors import (
    AdapterConnectionError,
    AdapterError,
    AdapterResponseError,
    AdapterTimeoutError,
)


class OneBotError(AdapterError):
    code = "ONEBOT_ERROR"
    message = "OneBot 调用失败"
    def __init__(self, action: str = "", *, retryable: bool = False):
        self.action = action
        self.retryable = retryable
        self.error_code = self.code
        super().__init__()


class OneBotConnectionError(OneBotError, AdapterConnectionError):
    code = "ONEBOT_CONNECTION_ERROR"
    message = "OneBot 连接失败"


class OneBotTimeoutError(OneBotError, AdapterTimeoutError):
    code = "ONEBOT_TIMEOUT"
    message = "OneBot 请求超时"


class OneBotAuthenticationError(OneBotError, AdapterResponseError):
    code = "ONEBOT_AUTHENTICATION_ERROR"
    message = "OneBot 认证失败"


class OneBotApiError(OneBotError, AdapterResponseError):
    code = "ONEBOT_API_ERROR"
    message = "OneBot 接口调用失败"


class OneBotInvalidResponseError(OneBotError, AdapterResponseError):
    code = "ONEBOT_INVALID_RESPONSE"
    message = "OneBot 响应格式无效"


class OneBotNotConnectedError(OneBotConnectionError):
    code = "ONEBOT_NOT_CONNECTED"
    message = "OneBot 未连接或账号离线"


class OneBotUnsupportedActionError(OneBotError, AdapterResponseError):
    code = "ONEBOT_UNSUPPORTED_ACTION"
    message = "OneBot 不支持该操作"


class OneBotRateLimitError(OneBotError, AdapterResponseError):
    code = "ONEBOT_RATE_LIMIT"
    message = "OneBot 请求受限"


class OneBotArgumentError(OneBotError):
    code = "ONEBOT_INVALID_ARGUMENT"
    message = "OneBot 调用参数无效"
