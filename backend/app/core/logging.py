import json
import logging
import re
from datetime import UTC, datetime


class SensitiveDataFilter(logging.Filter):
    def filter(self, record):
        text = record.getMessage()
        text = re.sub(r"(?i)bearer\s+[^\s,;\"']+", "Bearer [REDACTED]", text)
        text = re.sub(r"(?i)(password|access_token|token|cookie|session(?:[_ ]key)?|authorization)([\"']?\s*[:=]\s*)([^\r\n]+)",
                      r"\1\2[REDACTED]", text)
        record.msg, record.args = text, ()
        record.exc_info, record.exc_text = None, None
        return True


class SafeJsonFormatter(logging.Formatter):
    """Only fixed event names and allowlisted correlation fields; no exception payloads."""

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", "application_event"),
        }
        for key in ("execution_id", "account_id", "task_code", "status", "dependency", "stage", "duration",
                    "worker_id", "job_id", "retry_count", "node_id", "action", "count", "onebot_events_total",
                    "onebot_ws_connected", "onebot_ws_reconnect_total"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        return json.dumps(data, ensure_ascii=False)


def configure_logging() -> None:
    logger = logging.getLogger("app")
    handler = logging.StreamHandler()
    handler.addFilter(SensitiveDataFilter())
    handler.setFormatter(SafeJsonFormatter())
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for name in ("httpx", "httpcore", "websockets", "playwright"):
        third_party = logging.getLogger(name)
        third_party.handlers = [logging.NullHandler()]
        third_party.propagate = False
        third_party.setLevel(logging.CRITICAL)
