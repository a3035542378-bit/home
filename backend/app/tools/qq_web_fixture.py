"""仅测试站点：静态页面、无写操作、不模拟真实 QQ 页面。"""
from http.cookies import SimpleCookie


def fixture_html(path, headers):
    values = SimpleCookie()
    for line in headers.split("\r\n"):
        if line.lower().startswith("cookie:"):
            values.load(line.split(":", 1)[1].strip())
    authenticated = "fixture_account" in values
    states = {
        "/qq/login-required": "NOT_AUTHENTICATED", "/qq/device-verification": "NEED_DEVICE_VERIFICATION",
        "/qq/qr": "NEED_QR_LOGIN", "/qq/captcha": "NEED_CAPTCHA", "/qq/unknown": "UNKNOWN",
    }
    state = states.get(path, "AUTHENTICATED" if authenticated else "NOT_AUTHENTICATED")
    account_id = values["fixture_account"].value if authenticated else ""
    account_id = account_id if account_id.isdigit() else ""
    html = f'<!doctype html><title>QQ Web Fixture</title><div data-fixture-login="{state}" data-fixture-account="{account_id}"></div>'
    html += '<input type="password" value="fixture-private"><div data-sensitive>private-personal-content</div>'
    if path in {"/qq/task-center", "/qq/task-center-parse-error"}:
        key = "read" if path == "/qq/task-center" else "private-unrecognized-key"
        html += f'<section id="fixture-task-center" data-empty="false"><div data-task-key="{key}" data-status="COMPLETED"></div>'
        html += '<div data-task-key="visit" data-status="PENDING"></div><div data-task-key="reward" data-status="CLAIMABLE"></div></section>'
    if path == "/qq/task-center-empty":
        html += '<section id="fixture-task-center" data-empty="true"></section>'
    if path == "/qq/activity":
        html += '<section id="fixture-activity" data-empty="false"><div data-available="true"></div><div data-available="false"></div></section>'
    if path == "/qq/activity-parse-error":
        html += '<section id="fixture-activity" data-empty="false"><div data-available="invalid"></div></section>'
    if path == "/qq/activity-empty":
        html += '<section id="fixture-activity" data-empty="true"></section>'
    if path == "/qq/subrequest-blocked":
        html += '<iframe src="/forbidden-private"></iframe><img src="http://169.254.169.254/latest/meta-data/">'
    # 如果误开脚本或点击，验收请求记录能发现该写请求。
    html += '<button onclick="fetch(\'/write-action\', {method: \'POST\'})">领取</button>'
    return html


def fixture_state(account_id):
    return {"cookies": [{"name": "fixture_account", "value": str(account_id), "domain": "127.0.0.1",
                         "path": "/", "httpOnly": True, "secure": False, "sameSite": "Lax"}], "origins": []}
