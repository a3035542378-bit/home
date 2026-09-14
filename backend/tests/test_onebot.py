import httpx
import pytest
from pydantic import ValidationError

from app.adapters.errors import AdapterConnectionError, AdapterResponseError, AdapterTimeoutError
from app.adapters.onebot import OneBotAdapter
from app.core.config import Settings


def settings(**overrides):
    return Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:", **{
        "onebot_http_url": "http://napcat.test:3000", "onebot_retries": 0,
        "onebot_access_token": "mock-credential", **overrides,
    })


def response(data):
    return httpx.Response(200, json={"status": "ok", "retcode": 0, "data": data})


async def test_health_and_login():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        assert request.headers["Authorization"] == "Bearer mock-credential"
        if request.url.path == "/get_status":
            return response({"online": True, "good": True})
        return response({"user_id": 123456, "nickname": "本人"})

    async with OneBotAdapter(settings(), transport=httpx.MockTransport(handler)) as adapter:
        assert (await adapter.health_check()).online
        login = await adapter.get_login_info()
        assert login.user_id == 123456
    assert adapter.client.is_closed
    assert paths == ["/get_status", "/get_status", "/get_login_info"]


@pytest.mark.parametrize("error,expected", [
    (httpx.ConnectError, AdapterConnectionError),
    (httpx.ReadTimeout, AdapterTimeoutError),
    (httpx.ConnectTimeout, AdapterTimeoutError),
])
async def test_transport_errors(error, expected):
    def handler(request):
        raise error("sensitive-upstream-error")
    async with OneBotAdapter(settings(), transport=httpx.MockTransport(handler)) as adapter:
        with pytest.raises(expected) as caught:
            await adapter.health_check()
        assert "sensitive-upstream-error" not in str(caught.value)


@pytest.mark.parametrize("upstream", [
    httpx.Response(500), httpx.Response(401), httpx.Response(302, headers={"Location": "http://elsewhere"}),
    httpx.Response(200, text="not-json"), httpx.Response(200, json=[]),
    httpx.Response(200, json={"status": "failed", "retcode": 100, "data": None}),
    response({"online": "true", "good": True}), response({}),
    httpx.Response(200, json={"status": "ok", "retcode": True, "data": {}}),
])
async def test_invalid_responses(upstream):
    async with OneBotAdapter(settings(), transport=httpx.MockTransport(lambda _: upstream)) as adapter:
        with pytest.raises(AdapterResponseError):
            await adapter.health_check()


@pytest.mark.parametrize("online,good", [(False, True), (True, False), (False, False)])
async def test_offline(online, good):
    async with OneBotAdapter(settings(), transport=httpx.MockTransport(
        lambda _: response({"online": online, "good": good}),
    )) as adapter:
        with pytest.raises(AdapterConnectionError):
            await adapter.get_login_info()


async def test_invalid_login():
    def handler(request):
        return response({"online": True, "good": True}) if request.url.path == "/get_status" else response({"user_id": True})
    async with OneBotAdapter(settings(), transport=httpx.MockTransport(handler)) as adapter:
        with pytest.raises(AdapterResponseError):
            await adapter.get_login_info()


async def test_retry_and_recovery():
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("offline")
        return response({"online": True, "good": True})
    async with OneBotAdapter(settings(onebot_retries=1), transport=httpx.MockTransport(handler)) as adapter:
        assert (await adapter.health_check()).good
    assert calls == 2


async def test_unconfigured():
    async with OneBotAdapter(settings(onebot_http_url=None)) as adapter:
        with pytest.raises(AdapterConnectionError):
            await adapter.health_check()


def test_environment_loading(monkeypatch):
    monkeypatch.setenv("ONEBOT_HTTP_URL", "http://napcat.test:3000")
    monkeypatch.setenv("ONEBOT_WS_URL", "ws://napcat.test:3001")
    monkeypatch.setenv("ONEBOT_ACCESS_TOKEN", "mock-environment-secret")
    config = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")
    assert config.onebot_ws_url.get_secret_value() == "ws://napcat.test:3001"
    assert "mock-environment-secret" not in repr(config)
    assert "mock-environment-secret" not in config.model_dump_json()


@pytest.mark.parametrize("url", ["ftp://host", "http://user:password@host", "http://host?token=x"])
def test_invalid_url(url):
    with pytest.raises(ValidationError):
        settings(onebot_http_url=url)
