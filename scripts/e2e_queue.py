"""真实容器链路验收：仅使用无外部调用的 Mock 插件，保留执行审计。"""
import asyncio
from pathlib import Path
from uuid import uuid4

import httpx
from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[1]


async def docker(*args):
    process = await asyncio.create_subprocess_exec(
        "docker", *args, cwd=ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    output, _ = await process.communicate()
    if process.returncode:
        raise RuntimeError("Docker 验收命令失败")
    return output.decode().strip()


async def main():
    settings = Settings()
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=10,
                                 headers={"Authorization": "Bearer " + settings.admin_access_token.get_secret_value()}) as client:
        async def request(method, path, **kwargs):
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else None

        async def wait_for(execution_id, predicate, seconds=100):
            for _ in range(seconds * 4):
                record = await request("GET", "/api/executions/" + execution_id)
                if predicate(record):
                    return record
                await asyncio.sleep(0.25)
            raise AssertionError("执行记录未在预期时间内到达目标状态")

        codes = ["MOCK_SUCCESS", "MOCK_FAIL", "MOCK_TIMEOUT", "MOCK_NEED_USER_ACTION"]
        existing = {item["task_code"] for item in await request("GET", "/api/tasks")}
        for code in codes:
            if code not in existing:
                await request("POST", "/api/tasks", json={"task_code": code, "task_name": code,
                                                         "category": "MOCK"})
        account = await request("POST", "/api/accounts", json={
            "account_no": "queue-e2e-" + uuid4().hex[:12], "nickname": "队列验收临时账号", "platform": "WEB",
        })
        account_id = account["id"]
        for code in codes:
            await request("PUT", f"/api/accounts/{account_id}/tasks/{code}", json={"enabled": True})
        print("Mock definitions/account/config prepared", flush=True)

        for code, expected in [("MOCK_SUCCESS", "SUCCESS"), ("MOCK_FAIL", "FAILED"),
                               ("MOCK_NEED_USER_ACTION", "NEED_USER_ACTION")]:
            response = await client.post(f"/api/tasks/{code}/execute", json={"account_id": account_id})
            assert response.status_code == 202
            execution_id = response.json()["execution_id"]
            result = await wait_for(execution_id, lambda r: r["status"] not in {"PENDING", "RUNNING"})
            assert result["status"] == expected
            if code == "MOCK_FAIL":
                failed_id = execution_id
            print(f"API → Stream → Worker → {code}: {expected}", flush=True)

        retry = await request("POST", "/api/executions/retry-failed", json={"account_id": account_id})
        assert retry["created"] == 1
        child = await wait_for(retry["execution_ids"][0], lambda r: r["status"] == "FAILED")
        assert child["parent_execution_id"] == failed_id
        assert (await request("GET", "/api/executions/" + failed_id))["status"] == "FAILED"
        print("Retry: new child consumed, original FAILED preserved", flush=True)

        task = await request("POST", "/api/tasks/MOCK_TIMEOUT/execute", json={"account_id": account_id})
        running = await wait_for(task["execution_id"], lambda r: r["status"] == "RUNNING")
        containers = (await docker("compose", "ps", "-q", "worker")).splitlines()
        target = None
        for container in containers:
            hostname = await docker("inspect", "--format", "{{.Config.Hostname}}", container)
            if running["worker_id"].startswith(hostname + "-"):
                target = container
                break
        assert target, "未找到持有该执行的 Worker 容器"
        # 仅终止当前验收执行所属 Worker，且该 Worker 没有其他执行。
        workers = await request("GET", "/api/system/worker-status")
        owned = next((w for w in workers if w["worker_id"] == running["worker_id"]), None)
        if owned:
            assert set(owned["active_execution"]) <= {task["execution_id"]}
        await docker("kill", "--signal", "KILL", target)
        print("Worker SIGKILL sent; waiting for real lease expiration", flush=True)
        try:
            recovered = await wait_for(task["execution_id"], lambda r: r["status"] == "FAILED",
                                       int(settings.execution_lease_seconds) + 30)
            assert recovered["error_code"] == "WORKER_LEASE_EXPIRED"
            print("Lease recovery: FAILED / WORKER_LEASE_EXPIRED", flush=True)
        finally:
            await docker("compose", "up", "-d", "worker")
        await request("DELETE", f"/api/accounts/{account_id}")
        print("PASS: temporary account soft-deleted; audit history retained; Worker restored", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
