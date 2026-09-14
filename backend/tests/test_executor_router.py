from dataclasses import replace

import pytest
from pydantic import ValidationError
from test_browser_unit import config

from app.adapters.mobile import FakeMobileAdapter, MobileNotConfigured, UnconfiguredMobileAdapter
from app.executors.catalog import INFRASTRUCTURE, OPERATIONS, VERIFICATIONS
from app.executors.errors import ExecutorRoutingError
from app.executors.models import CapabilityStatus as S
from app.executors.models import ExecutorRuntime, RiskLevel, RoutingContext
from app.executors.models import ExecutorType as E
from app.executors.models import OperationCode as O
from app.executors.models import VerificationLevel as V
from app.executors.resolver import CapabilityResolver
from app.executors.router import ExecutorRouter

CODE = O.QQ_TASK_CENTER_READ


def ready(**changes):
    values = {"configured": True, "ready": True, "authenticated": True, "state_present": True,
              "site_configured": True,
              "capabilities": frozenset({cap for operation in OPERATIONS.values() for cap in operation.capabilities})}
    return ExecutorRuntime(**(values | changes))


def context(**changes):
    return RoutingContext(1, runtime={E.BROWSER: ready(**changes), E.MOBILE: ready(**changes), E.ONEBOT: ready(**changes)})


def verified_router(priorities=None, operations=OPERATIONS):
    # 仅单测模拟未来可信证据，不修改默认产品登记表。
    levels = {(code, executor): V.REAL_ENV_VERIFIED for code, spec in operations.items()
              for executor in spec.allowed_executors}
    return ExecutorRouter(CapabilityResolver(operations=operations, verifications=levels), priorities=priorities)


@pytest.mark.parametrize("code", list(O))
def test_operation_metadata(code):
    operation = OPERATIONS[code]
    assert operation.code == code and E.NONE not in operation.allowed_executors
    assert len(set(operation.allowed_executors)) == len(operation.allowed_executors)
    if operation.implemented:
        assert operation.read_only and operation.idempotent and operation.risk_level == "SAFE_READONLY"
        assert operation.side_effect_level == "NONE" and operation.capabilities
    else:
        assert not operation.read_only and operation.risk_level == "HIGH_SIDE_EFFECT"


@pytest.mark.parametrize("code", list(O))
@pytest.mark.parametrize("mode", ["PRODUCTION", "DIAGNOSTIC"])
async def test_current_manifest_never_selects_production(code, mode):
    result = await ExecutorRouter().resolve(code, context(), mode=mode)
    assert result.selected_executor is None
    assert all(c.status != S.AVAILABLE for c in result.candidates)
    assert INFRASTRUCTURE["browser.chromium"] == V.REAL_ENV_VERIFIED
    assert all(level != V.REAL_ENV_VERIFIED for level in VERIFICATIONS.values())


async def test_verification_levels_and_mobile_placeholder():
    router = ExecutorRouter()
    ctx = RoutingContext(1)
    onebot = await router.resolve(O.QQ_ACCOUNT_STATUS_READ, ctx)
    browser = await router.resolve(CODE, ctx)
    assert onebot.candidates[0].verification_level == V.MOCK_ONLY
    assert browser.candidates[0].verification_level == V.FIXTURE_VERIFIED
    assert browser.candidates[0].status == S.NOT_VERIFIED
    assert browser.candidates[1].status == S.NOT_CONFIGURED
    assert browser.candidates[1].verification_level == V.NOT_VERIFIED


@pytest.mark.parametrize("changes,status", [({"configured": False}, S.NOT_CONFIGURED),
    ({"ready": False}, S.SUPPORTED_NOT_READY), ({"state_present": False}, S.NOT_AUTHENTICATED),
    ({"authenticated": None}, S.SUPPORTED_NOT_READY), ({"need_user_action": True}, S.NEED_USER_ACTION),
    ({"degraded": True}, S.DEGRADED), ({"capabilities": frozenset()}, S.UNSUPPORTED),
    ({"site_configured": False}, S.NOT_CONFIGURED), ({"site_operations": frozenset()}, S.NOT_CONFIGURED)])
async def test_runtime_readiness(changes, status):
    result = await verified_router().resolve(CODE, context(**changes), preferred_executor=E.BROWSER)
    assert result.candidates[0].status == status and result.selected_executor is None


async def test_safe_readonly_priority_and_explicit_executor():
    router = verified_router({CODE: [E.MOBILE, E.BROWSER]})
    assert (await router.resolve(CODE, context())).selected_executor == E.MOBILE
    assert (await router.resolve(CODE, context(), preferred_executor=E.BROWSER)).selected_executor == E.BROWSER
    assert await router.require(CODE, context()) == E.MOBILE
    ctx = context()
    ctx.runtime[E.MOBILE] = ready(capabilities=frozenset())
    assert (await router.resolve(CODE, ctx)).selected_executor == E.BROWSER
    assert (await router.resolve(CODE, ctx, preferred_executor=E.MOBILE)).selected_executor is None


async def test_user_action_blocks_other_available_executor():
    ctx = context()
    ctx.runtime[E.BROWSER] = ready(need_user_action=True)
    result = await verified_router({CODE: [E.MOBILE]}).resolve(CODE, ctx)
    assert result.selected_executor is None and result.status == S.NEED_USER_ACTION
    with pytest.raises(ExecutorRoutingError, match="当前 Operation") as error:
        await verified_router().resolve_fallback(CODE, ctx, failed_executor=E.BROWSER,
                                                 failure_status=S.DEGRADED, enabled=True)
    assert error.value.code == "EXECUTOR_NEED_USER_ACTION"


@pytest.mark.parametrize("status", [S.NEED_USER_ACTION, S.NOT_AUTHENTICATED, S.NOT_VERIFIED])
async def test_fallback_cannot_bypass_failure(status):
    with pytest.raises(ExecutorRoutingError):
        await verified_router().resolve_fallback(CODE, context(), failed_executor=E.BROWSER,
                                                 failure_status=status, enabled=True)


async def test_explicit_readonly_fallback_and_default_disabled():
    router = verified_router()
    with pytest.raises(ExecutorRoutingError):
        await router.resolve_fallback(CODE, context(), failed_executor=E.BROWSER, failure_status=S.DEGRADED)
    result = await router.resolve_fallback(CODE, context(), failed_executor=E.BROWSER,
                                          failure_status=S.DEGRADED, enabled=True)
    assert result.selected_executor == E.MOBILE


@pytest.mark.parametrize("risk", [RiskLevel.HIGH_SIDE_EFFECT, RiskLevel.LOW_SIDE_EFFECT])
async def test_risk_never_selects_or_falls_back(risk):
    operations = dict(OPERATIONS)
    operations[CODE] = replace(operations[CODE], risk_level=risk, read_only=False)
    router = verified_router(operations=operations)
    result = await router.resolve(CODE, context(), preferred_executor=E.BROWSER)
    assert result.selected_executor is None and result.reason == "RISK_POLICY_BLOCKED"
    with pytest.raises(ExecutorRoutingError):
        await router.resolve_fallback(CODE, context(), failed_executor=E.BROWSER,
                                      failure_status=S.DEGRADED, enabled=True)


@pytest.mark.parametrize("platform,active", [("OTHER", True), ("QQ", False)])
async def test_account_preconditions(platform, active):
    assert (await verified_router().resolve(CODE, replace(context(), platform=platform, active=active))).selected_executor is None


async def test_error_contract():
    router = ExecutorRouter()
    with pytest.raises(ExecutorRoutingError) as error:
        await router.require(CODE, context())
    assert error.value.code == "EXECUTOR_NOT_VERIFIED"
    with pytest.raises(ExecutorRoutingError) as error:
        await router.resolve("UNKNOWN", context())
    assert error.value.code == "OPERATION_UNSUPPORTED"
    with pytest.raises(ExecutorRoutingError):
        await router.resolve(CODE, context(), preferred_executor=E.ONEBOT)


@pytest.mark.parametrize("value", [{"UNKNOWN": ["ONEBOT"]}, {CODE: ["ONEBOT"]}, {CODE: []},
                                   {CODE: ["BROWSER", "BROWSER"]}, {CODE: ["NONE"]}])
def test_invalid_priority_settings(tmp_path, value):
    with pytest.raises(ValidationError):
        config(tmp_path, executor_priorities=value)


async def test_mobile_has_no_real_implementation():
    mobile, fake = UnconfiguredMobileAdapter(), FakeMobileAdapter()
    assert not await mobile.health_check() and not any(mobile.capabilities().values())
    with pytest.raises(MobileNotConfigured):
        await mobile.read_page()
    assert await fake.health_check() and (await fake.read_page())["fixture"]
    assert not fake.capabilities()["mobile.app.launch"]


async def test_login_missing_blocks_cross_executor_selection():
    ctx = context()
    ctx.runtime[E.BROWSER] = ready(authenticated=False)
    result = await verified_router().resolve(CODE, ctx)
    assert result.selected_executor is None and result.error_code == "EXECUTOR_NEED_USER_ACTION"


async def test_invalid_router_values_have_uniform_errors():
    with pytest.raises(ExecutorRoutingError):
        await ExecutorRouter().resolve(CODE, context(), mode="INVALID")
    with pytest.raises(ExecutorRoutingError):
        await verified_router().resolve_fallback(CODE, context(), failed_executor="INVALID",
                                                 failure_status=S.DEGRADED, enabled=True)


async def test_resolver_returns_capability_resolution():
    from app.executors.models import CapabilityResolution
    result = await CapabilityResolver().resolve(CODE, RoutingContext(1))
    assert isinstance(result, CapabilityResolution) and result.operation == CODE
    assert result.selected_executor is None and result.candidates[0].verification_level == V.FIXTURE_VERIFIED
