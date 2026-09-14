from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, field_validator


class ScreenshotPolicy(StrEnum):
    FAILURE_ONLY = "FAILURE_ONLY"
    DISABLED = "DISABLED"


@dataclass(frozen=True)
class Selector:
    kind: Literal["css", "text", "role"]
    value: str
    name: str | None = None


class BrowserEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    final_url: str | None = None
    screenshot_path: str | None = None
    page_title: None = None

    @field_validator("final_url")
    @classmethod
    def remove_sensitive_url_parts(cls, value):
        return safe_origin(value) if value else None


def safe_origin(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    # 路径、查询参数、fragment、用户名均不作为执行证据。
    host = f"[{parsed.hostname}]" if ':' in parsed.hostname else parsed.hostname
    return f"{parsed.scheme}://{host}" + (f":{parsed.port}" if parsed.port else "")


def account_key(account_id):
    if type(account_id) is not int or account_id <= 0:
        from app.adapters.browser.exceptions import BrowserSessionError
        raise BrowserSessionError()
    return str(account_id)
