"""从现有 HTTP API 投递 Browser Probe，由真实 Docker Worker 执行。"""

import asyncio
import json
from uuid import uuid4

import httpx
from app.core.config import Settings
from app.core.logging import configure_logging


async def run():
    configure_logging()
    settings = Settings()
    listing = await asyncio.create_subprocess_exec(
        "docker", "compose", "ps", "-q", "worker", stdout=asyncio.subprocess.PIPE
    )
    output, _ = await listing.communicate()
    if listing.returncode or len(output.splitlines()) != 1:
        raise RuntimeError("验收需要恰好一个 Worker，保证临时 loopback 站点可达")
    site = await asyncio.create_subprocess_exec(
        "docker",
        "compose",
        "exec",
        "-T",
        "worker",
        "python",
        "-m",
        "app.tools.probe_site",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    account = None
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8000",
        timeout=10,
        headers={
            "Authorization": "Bearer " + settings.admin_access_token.get_secret_value()
        },
    ) as client:

        async def request(method, path, **kwargs):
            response = await client.request(method, path, **kwargs)
            if not response.is_success:
                raise RuntimeError(f"验收 API 返回 HTTP {response.status_code}")
            return response.json() if response.content else None

        try:
            origin = (
                (await asyncio.wait_for(site.stdout.readline(), 10)).decode().strip()
            )
            if not origin.startswith("http://127.0.0.1:"):
                raise RuntimeError("临时站点未启动")
            existing = set()
            offset = 0
            while True:
                rows = await request("GET", f"/api/tasks?offset={offset}&limit=100")
                existing.update(row["task_code"] for row in rows)
                if len(rows) < 100:
                    break
                offset += 100
            for code, executor in (
                ("ONEBOT_READONLY_PROBE", "ONEBOT"),
                ("BROWSER_READONLY_PROBE", "BROWSER"),
                ("COMPOSITE_PROBE", "NONE"),
            ):
                if code not in existing:
                    await request(
                        "POST",
                        "/api/tasks",
                        json={
                            "task_code": code,
                            "task_name": code,
                            "category": "PROBE",
                            "executor_type": executor,
                            "default_enabled": False,
                        },
                    )
            account = await request(
                "POST",
                "/api/accounts",
                json={
                    "account_no": "probe-" + uuid4().hex,
                    "platform": "WEB",
                    "nickname": "临时浏览器诊断",
                },
            )
            code = "BROWSER_READONLY_PROBE"
            await request(
                "PUT",
                f"/api/accounts/{account['id']}/tasks/{code}",
                json={
                    "enabled": True,
                    "config_json": {
                        "url": origin + "/simple",
                        "expected_title": "Browser fixture",
                        "expected_text": "Local fixture",
                    },
                },
            )
            execution = await request(
                "POST", f"/api/tasks/{code}/execute", json={"account_id": account["id"]}
            )
            async with asyncio.timeout(75):
                while execution["status"] in {"PENDING", "RUNNING"}:
                    await asyncio.sleep(0.3)
                    execution = await request(
                        "GET", f"/api/executions/{execution['execution_id']}"
                    )
            if execution["status"] != "SUCCESS":
                raise RuntimeError(
                    "Browser Probe 失败：" + str(execution["error_code"])
                )
            result = execution["result_json"]
            assert result["evidence"] == {
                "title": "Browser fixture",
                "final_url": origin,
                "verification": {"title": True, "text": True, "http": True},
            }
            assert not any(
                key in json.dumps(result).lower()
                for key in ("cookie", "token", "storage_state", "fixture-private")
            )
            return {
                "overall": "PASS",
                "execution_id": execution["execution_id"],
                "worker_id": execution["worker_id"],
                "status": execution["status"],
                "evidence": result["evidence"],
                "task_version": result["task_version"],
                "plugin_version": result["plugin_version"],
                "real_onebot": "REAL_ONEBOT_TASK_NOT_TESTED",
            }
        finally:
            try:
                if account:
                    await request(
                        "PATCH",
                        f"/api/accounts/{account['id']}/tasks",
                        json={"enabled": False},
                    )
                    # 保留执行审计；只软删除本工具创建的临时账号。
                    response = await client.delete(f"/api/accounts/{account['id']}")
                    if response.status_code not in {204, 409}:
                        raise RuntimeError("临时账号清理失败")
            finally:
                site.stdin.close()
                await asyncio.wait_for(site.wait(), 10)


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))
