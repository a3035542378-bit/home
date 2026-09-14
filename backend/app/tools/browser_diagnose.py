"""在本地页面验证浏览器，临时状态和密钥在退出后清理。"""
import asyncio
import json
import tempfile

from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.adapters.browser import BrowserAdapter, Selector
from app.adapters.browser.exceptions import BrowserError
from app.core.config import Settings
from app.core.logging import configure_logging
from app.tools.browser_site import browser_site


async def diagnose():
    report = {}
    with tempfile.TemporaryDirectory(prefix='browser-diagnose-') as directory:
        settings = Settings(_env_file=None, database_url='sqlite+aiosqlite:///:memory:',
            browser_state_dir=directory, browser_storage_key=SecretStr(Fernet.generate_key().decode()))
        adapter = BrowserAdapter(settings)
        try:
            await adapter.start()
            report['startup'] = 'PASS'
            async with browser_site() as origin:
                async with await adapter.create_session(1) as session:
                    report['context'] = 'PASS'
                    page = await session.new_page()
                    await page.goto(origin+'/form')
                    report['navigation'] = 'PASS'
                    await page.fill('#name','fixture')
                    assert await page.evaluate("document.querySelector('#name').value") == 'fixture'
                    report['fill'] = 'PASS'
                    await page.click(Selector('role','button','Go'))
                    assert await page.text('#result') == 'clicked'
                    report['click'] = 'PASS'
                    await page.evaluate("localStorage.setItem('fixture','A');document.cookie='fixture=A;path=/'")
                    await session.save_state()
                async with await adapter.create_session(1, restore_state=True) as restored:
                    page = await restored.new_page()
                    await page.goto(origin+'/storage')
                    assert await page.evaluate("localStorage.getItem('fixture')") == 'A'
                    assert 'fixture=A' in await page.evaluate('document.cookie')
                async with await adapter.create_session(2) as isolated:
                    page = await isolated.new_page()
                    await page.goto(origin+'/storage')
                    assert await page.evaluate("localStorage.getItem('fixture')") is None
                    assert 'fixture=A' not in await page.evaluate('document.cookie')
                report['storage'] = report['account_isolation'] = 'PASS'
        except BrowserError as exc:
            report['error_code'] = exc.code
        finally:
            await adapter.stop()
            report['shutdown'] = 'PASS' if not adapter.manager.is_connected and not adapter.manager.sessions else 'FAIL'
    report['overall'] = 'PASS' if all(report.get(key) == 'PASS' for key in (
        'startup','context','navigation','click','fill','storage','account_isolation','shutdown',
    )) else 'FAIL'
    return report


def main():
    configure_logging()
    try:
        result = asyncio.run(diagnose())
    except Exception:  # noqa: BLE001 - 终端不输出第三方错误或页面内容
        result = {'overall':'FAIL','error_code':'BROWSER_DIAGNOSE_ERROR'}
    print(json.dumps(result, indent=2))
    return 0 if result['overall'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
