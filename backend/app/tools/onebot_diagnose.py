"""只读 NapCat 诊断；不修改节点、账号、任务或真实凭据配置。"""
import argparse
import asyncio
import json
import logging
import re
import secrets
from time import perf_counter

from pydantic import SecretStr

from app.adapters.onebot import OneBotAdapter
from app.adapters.onebot.events import EventBus, MetaEvent, UnknownEvent
from app.adapters.onebot.exceptions import OneBotError, OneBotUnsupportedActionError
from app.adapters.onebot.websocket_client import OneBotWebSocketClient
from app.core.config import Settings
from app.core.database import Database
from app.core.errors import BusinessError
from app.core.logging import configure_logging
from app.services.onebot import OneBotService
from app.services.unit_of_work import UnitOfWork

READ_ACTIONS = frozenset({
    'get_status', 'get_version_info', 'get_login_info', 'get_friend_list',
    'get_group_list', 'get_group_info', 'get_stranger_info',
})
logger = logging.getLogger('app.onebot.diagnose')


class ReadOnlyOneBotAdapter(OneBotAdapter):
    async def call(self, action, params=None):
        if action not in READ_ACTIONS:
            raise OneBotUnsupportedActionError()
        return await super().call(action, params)


def public_text(value, credential):
    text = str(value)
    if credential:
        text = text.replace(credential, '[REDACTED]')
    return re.sub(r'[^a-zA-Z0-9 ._+\[\]-]', '_', text)[:128]


def masked_id(value):
    text = str(value)
    return '****' + (text[-4:] if len(text) > 4 else '')


async def websocket_probe(config, expected_user_id, seconds, observe_reconnect=False):
    bus = EventBus()
    result = {name: 'NOT_TESTED' for name in (
        'connect', 'authentication', 'heartbeat', 'event_parse',
        'disconnect_detection', 'automatic_reconnect',
    )}
    finished = asyncio.Event()
    connected_once, disconnected, recovered = False, False, False
    heartbeat_before_disconnect = False

    async def state(value):
        nonlocal connected_once, disconnected, recovered
        if value == 'CONNECTED':
            recovered = disconnected
            connected_once = True
            result['connect'] = 'PASS'
            result['authentication'] = 'ACCEPTED' if config.onebot_access_token.get_secret_value() else 'NOT_CONFIGURED'
        elif value == 'AUTH_FAILED':
            result['authentication'] = 'AUTH_FAILED'
            finished.set()
        elif value == 'DISCONNECTED' and connected_once and heartbeat_before_disconnect:
            disconnected = True
            result['disconnect_detection'] = 'PASS'

    async def event(item):
        nonlocal heartbeat_before_disconnect
        if isinstance(item, UnknownEvent):
            result['event_parse'] = 'FAIL'
            return
        if isinstance(item, MetaEvent) and item.meta_event_type == 'heartbeat':
            if item.self_id != expected_user_id or item.status is None:
                result['heartbeat'] = 'IDENTITY_OR_SCHEMA_MISMATCH'
                finished.set()
                return
            if not item.status.online or not item.status.good:
                result['heartbeat'] = 'OFFLINE'
                finished.set()
                return
            result['heartbeat'] = 'PASS'
            if result['event_parse'] != 'FAIL':
                result['event_parse'] = 'PASS'
            heartbeat_before_disconnect = True
            if recovered:
                result['automatic_reconnect'] = 'PASS'
            if not observe_reconnect or recovered:
                finished.set()

    bus.subscribe(event)
    client = OneBotWebSocketClient(config, bus, state)
    receiver, consumer = asyncio.create_task(client.run()), asyncio.create_task(bus.run())
    try:
        try:
            await asyncio.wait_for(finished.wait(), seconds)
        except TimeoutError:
            result['observation'] = 'TIMEOUT'
    finally:
        client.stop_event.set()
        receiver.cancel()
        consumer.cancel()
        await asyncio.gather(receiver, consumer, return_exceptions=True)
    result['reconnect_attempts'] = client.metrics['onebot_ws_reconnect_total']
    return result


async def diagnose(config, expected_account_no, *, adapter_factory=ReadOnlyOneBotAdapter,
                   ws_probe=websocket_probe, ws_seconds=75, observe_reconnect=False,
                   wrong_token=False):
    report = {'overall': 'FAIL', 'actions': {}, 'identity': 'NOT_TESTED',
              'websocket': {'status': 'NOT_TESTED'}, 'source': 'LIVE_ENDPOINT'}
    real_credential = config.onebot_access_token.get_secret_value()
    if wrong_token:
        # 临时覆盖仅存在当前进程内，不回写 .env 或节点。
        config = config.model_copy(update={'onebot_access_token': SecretStr(secrets.token_urlsafe(32)),
                                           'onebot_max_retries': 0})
    async with adapter_factory(config) as adapter:
        async def check(name, method, **params):
            start = perf_counter()
            try:
                value = await method(**params)
                report['actions'][name] = {'status': 'PASS', 'elapsed_ms': round((perf_counter()-start)*1000, 2)}
                if isinstance(value, list):
                    report['actions'][name]['count'] = len(value)
                return value
            except OneBotError as exc:
                report['actions'][name] = {'status': 'FAIL', 'error_code': exc.code,
                                          'elapsed_ms': round((perf_counter()-start)*1000, 2)}
                return None

        health = await check('health_check', adapter.health_check)
        if wrong_token:
            report['http_authentication'] = 'AUTH_FAILED' if report['actions']['health_check'].get('error_code') == 'ONEBOT_AUTHENTICATION_ERROR' else 'FAIL'
            report['websocket'] = await ws_probe(config, 0, ws_seconds, False)
            report['overall'] = 'AUTH_REJECTION_PASS' if report['http_authentication'] == 'AUTH_FAILED' and report['websocket'].get('authentication') == 'AUTH_FAILED' else 'FAIL'
            return report
        version = await check('get_version_info', adapter.get_version_info)
        status = await check('get_status', adapter.get_status)
        login = await check('get_login_info', adapter.get_login_info)
        if version:
            report['version'] = {key: public_text(value, real_credential) for key, value in version.model_dump().items()}
        if login:
            report['qq'] = {'user_id': masked_id(login.user_id), 'logged_in': bool(status and status.online)}
        if not login or not health:
            return report
        if str(login.user_id) != expected_account_no:
            report['identity'] = 'ONEBOT_IDENTITY_MISMATCH'
            return report
        report['identity'] = 'PASS'
        await check('get_friend_list', adapter.get_friend_list)
        groups = await check('get_group_list', adapter.get_group_list)
        if groups:
            await check('get_group_info', adapter.get_group_info, group_id=groups[0].group_id)
        else:
            report['actions']['get_group_info'] = {'status': 'NOT_TESTED', 'reason': 'NO_GROUP_AVAILABLE'}
        await check('get_stranger_info', adapter.get_stranger_info, user_id=login.user_id)
        report['websocket'] = await ws_probe(config, login.user_id, ws_seconds, observe_reconnect)
        required = ('health_check', 'get_version_info', 'get_status', 'get_login_info', 'get_friend_list', 'get_group_list', 'get_stranger_info')
        passed = all(report['actions'][name]['status'] == 'PASS' for name in required)
        passed = passed and report['actions']['get_group_info']['status'] != 'FAIL'
        passed = passed and all(report['websocket'].get(name) == 'PASS' for name in ('connect', 'heartbeat', 'event_parse'))
        if observe_reconnect:
            passed = passed and report['websocket'].get('automatic_reconnect') == 'PASS'
        report['overall'] = 'READ_ONLY_CHECKS_PASS' if passed else 'FAIL'
        return report


async def run(node_id=None, account_id=None, *, ws_seconds=75, observe_reconnect=False, wrong_token=False):
    settings = Settings()
    database = Database(settings)
    uow = UnitOfWork(database.sessions)
    service = OneBotService(uow, settings)
    try:
        if node_id is None:
            return {'overall': 'WAITING_FOR_REAL_NAPCAT', 'real_status': 'REAL_NAPCAT_NOT_TESTED',
                    'onebot_node_count': len(await service.endpoints()), 'next_step': 'CONFIGURE_NODE_AND_ACCOUNT_THEN_SPECIFY_NODE_ID'}
        endpoint = await service.endpoint(node_id)
        config = service.connection_settings(endpoint)
        if config.onebot_http_url is None or config.onebot_ws_url is None:
            return {'overall': 'WAITING_FOR_REAL_NAPCAT', 'real_status': 'REAL_NAPCAT_NOT_TESTED', 'error_code': 'NODE_ENDPOINT_NOT_CONFIGURED'}
        async with uow.transaction() as repos:
            accounts = await repos.accounts.for_node(node_id)
            selected = [a for a in accounts if a.id == account_id] if account_id else accounts
            if len(selected) != 1 or selected[0].platform != 'QQ':
                raise BusinessError('DIAGNOSE_ACCOUNT_REQUIRED', '请指定已绑定此节点的 QQ 账号')
            expected = selected[0].account_no
        result = await diagnose(config, expected, ws_seconds=ws_seconds,
                                observe_reconnect=observe_reconnect, wrong_token=wrong_token)
        result['node'] = {'id': node_id, 'type': 'ONEBOT'}
        return result
    finally:
        await service.aclose()
        await database.close()


def main():
    parser = argparse.ArgumentParser(description='OneBot 只读诊断，不执行任何 WRITE action')
    parser.add_argument('--node-id', type=int)
    parser.add_argument('--account-id', type=int)
    parser.add_argument('--ws-seconds', type=float, default=75)
    parser.add_argument('--observe-reconnect', action='store_true', help='观察期间手动停止并恢复 NapCat，脚本不管理外部进程')
    parser.add_argument('--wrong-token', action='store_true', help='仅在诊断进程中临时使用错误凭据')
    args = parser.parse_args()
    if not 0 < args.ws_seconds <= 600:
        parser.error('ws-seconds 必须在 0 到 600 秒之间')
    configure_logging()
    try:
        report = asyncio.run(run(args.node_id, args.account_id, ws_seconds=args.ws_seconds,
                                observe_reconnect=args.observe_reconnect, wrong_token=args.wrong_token))
    except (BusinessError, OneBotError) as exc:
        report = {'overall': 'FAIL', 'error_code': exc.code}
    except KeyboardInterrupt:
        report = {'overall': 'INTERRUPTED'}
    except Exception:  # noqa: BLE001 - CLI 不能泄露配置或网络异常原文
        logger.error('diagnose_failed', extra={'event':'diagnose_failed'})
        report = {'overall': 'FAIL', 'error_code': 'DIAGNOSE_ERROR'}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['overall'] in {'READ_ONLY_CHECKS_PASS', 'AUTH_REJECTION_PASS'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
