import logging

logger = logging.getLogger("app.errors")


class BusinessError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        logger.warning("business_error", extra={"event": "business_error", "status": code})
