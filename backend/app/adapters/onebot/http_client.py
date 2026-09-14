import asyncio
import logging
from collections import Counter
from typing import Any

import httpx
from pydantic import ValidationError

from app.adapters.onebot.capability import ACTIONS
from app.adapters.onebot.exceptions import (
    OneBotApiError,
    OneBotArgumentError,
    OneBotAuthenticationError,
    OneBotConnectionError,
    OneBotError,
    OneBotInvalidResponseError,
    OneBotNotConnectedError,
    OneBotRateLimitError,
    OneBotTimeoutError,
    OneBotUnsupportedActionError,
)
from app.adapters.onebot.retry_scope import worker_owns_retry
from app.adapters.onebot.schemas import INPUT_MODELS, AdapterResponse

logger = logging.getLogger("app.onebot.http")


class OneBotHttpClient:
    def __init__(self, settings, *, transport=None):
        self.settings = settings
        self.metrics = Counter()
        credential = settings.onebot_access_token.get_secret_value()
        self.client = httpx.AsyncClient(
            headers={"Authorization": "Bearer " + credential} if credential else {},
            timeout=httpx.Timeout(settings.onebot_http_timeout or settings.onebot_timeout_seconds,
                                  connect=settings.onebot_connect_timeout),
            transport=transport, follow_redirects=False, trust_env=False,
        )

    async def aclose(self):
        await self.client.aclose()

    async def call(self, action: str, params: dict[str, Any] | None = None) -> AdapterResponse:
        metadata = ACTIONS.get(action)
        if metadata is None:
            raise OneBotUnsupportedActionError()
        try:
            params = INPUT_MODELS[action].model_validate(params or {}).model_dump()
        except ValidationError:
            raise OneBotArgumentError(action) from None
        if self.settings.onebot_http_url is None:
            raise OneBotNotConnectedError(action)
        url = self.settings.onebot_http_url.get_secret_value().rstrip("/") + "/" + action
        retries = self.settings.onebot_max_retries
        if retries is None:
            retries = min(self.settings.onebot_retries, 2)
        delegated = worker_owns_retry.get() and metadata.retryable
        attempts = 1 if delegated else 1 + (retries if metadata.retryable else 0)
        for attempt in range(attempts):
            self.metrics["onebot_http_requests_total"] += 1
            try:
                response = await self.client.post(url, json=params or {})
                if response.status_code in {401, 403}:
                    raise OneBotAuthenticationError(action)
                if response.status_code == 429:
                    raise OneBotRateLimitError(action)
                if response.status_code == 404:
                    raise OneBotUnsupportedActionError(action)
                if response.status_code >= 500:
                    raise OneBotApiError(action, retryable=True)
                if response.status_code != 200:
                    raise OneBotApiError(action)
                envelope = AdapterResponse.model_validate(response.json())
                if envelope.retcode == 1404:
                    raise OneBotUnsupportedActionError(action)
                if envelope.status != "ok" or envelope.retcode != 0:
                    raise OneBotApiError(action)
                # 不把第三方自由文本带到调用方或日志中。
                return envelope.model_copy(update={"message": "", "wording": ""})
            except httpx.TimeoutException:
                error = OneBotTimeoutError(action, retryable=True)
            except httpx.TransportError:
                error = OneBotConnectionError(action, retryable=True)
            except (ValidationError, ValueError, httpx.DecodingError, httpx.InvalidURL):
                error = OneBotInvalidResponseError(action)
            except OneBotError as exc:
                error = exc
            self.metrics["onebot_http_errors_total"] += 1
            logger.warning("onebot_http_error", extra={"event": "onebot_http_error",
                           "action": action, "status": error.code, "retry_count": attempt})
            if not error.retryable or attempt + 1 == attempts:
                # 只读业务可把预算完整交给 Worker；默认模式仍在本层耗尽后停止。
                error.retryable = bool(delegated and error.retryable)
                raise error from None
            await asyncio.sleep(0.1 * 2 ** attempt)
        raise OneBotConnectionError(action)
