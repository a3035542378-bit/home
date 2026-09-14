from typing import Any

SENSITIVE_KEYS = {"password", "token", "cookie", "session", "authorization", "secret", "storage_state", "localstorage", "sessionstorage"}


def reject_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        for key, child in value.items():
            if any(word in key.lower() for word in SENSITIVE_KEYS):
                raise ValueError("敏感字段必须通过独立凭据提供器管理")
            reject_secrets(child)
    elif isinstance(value, list):
        for child in value:
            reject_secrets(child)
    return value
