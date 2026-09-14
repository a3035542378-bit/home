import logging

logger = logging.getLogger("app.adapter")


class AdapterError(Exception):
    retryable = False
    code = "ADAPTER_ERROR"
    message = "外部系统调用失败"

    def __init__(self):
        super().__init__(self.message)
        logger.warning("adapter_error", extra={"event": "adapter_error", "status": self.code})


class AdapterConnectionError(AdapterError):
    retryable = True
    code = "ADAPTER_CONNECTION_ERROR"
    message = "外部系统无法连接或账号离线"


class AdapterTimeoutError(AdapterError):
    retryable = True
    code = "ADAPTER_TIMEOUT"
    message = "外部系统响应超时"


class AdapterResponseError(AdapterError):
    code = "ADAPTER_INVALID_RESPONSE"
    message = "外部系统返回无效响应"
