# Task Plugin 开发规范（Phase 8A）

任务是受信任的 Python 工程代码，只编排业务检查与 Adapter 能力。不得访问 SQL、Session、Redis、httpx、requests、Playwright 或 NapCat HTTP。
账号和执行信息来自 TaskContext；业务数据由 Service/Repository 准备后注入。插件返回 TaskResult，不能自行更新 Execution。

## 新增插件

在 `backend/app/tasks/plugins/` 的包内新增 Python 文件，继承 BaseTask，使用 `@register_task` 注册。
子目录应有 `__init__.py`，其中不维护任务清单。load_builtin_tasks 启动时递归导入这个固定受信任包，同时兼容原 builtin 包；
不接受 HTTP 上传、外部目录或用户提供的模块路径。新增任务不修改 Engine。
部署后通过 POST /api/tasks 登记对应定义，通过账号任务配置 API 显式启用。代码注册与数据库定义是两个步骤。
重复 task_code、非 BaseTask、未实现 async execute 会被拒绝。新增后重建 API、Worker 和 Scheduler 镜像。

## 生命周期与上下文

Engine 顺序执行：读取插件 → Pydantic 配置校验 → 按账号/Node 注入 Adapter → 检查能力 → execute → 校验结果 → 统一落库。
TaskContext 提供 account、execution_id、config、validated_config、get_adapter、set_stage 和类型化浏览器证据接口。
config 是原始只读约定的配置映射；新插件只能使用通过 config_schema 校验后的 validated_config。
配置校验失败返回 FAILED / TASK_CONFIG_INVALID，不会进入 Adapter provider。

本阶段不增加 prepare/verify/cleanup 抽象钩子。execute 内执行前置检查、只读动作、验证、返回结果。
用 `async with await browser.create_session(...)` 回收 Session；Worker 的 ScopedBrowserAdapter 还会在异常/取消时兜底回收。
插件不得启动或关闭进程级 Browser，也不能吞掉 CancelledError。

## Metadata

| 字段 | Probe 值 / 约定 |
| --- | --- |
| task_code / task_name | 稳定代码和中文显示名 |
| task_version / plugin_version | 当前均为 1.0.0，每次执行由 Engine 写入结果 |
| config_schema | Pydantic BaseModel 类，extra=forbid，隐藏输入错误详情 |
| required_capabilities | 按 Adapter 分组的能力集合 |
| idempotent / read_only | Probe 均为 true |
| side_effect_level | NONE、LOW、HIGH；Probe 为 NONE |
| risk_level | TaskRiskLevel：SAFE_READONLY、LOW_SIDE_EFFECT、HIGH_SIDE_EFFECT |
| diagnostic_only / scheduled | Probe 为 true / false |
| task_type / category | DIAGNOSTIC / PROBE |
| timeout_seconds | OneBot 10、Browser 30、Composite 45 秒 |
| retry_policy | 可以重试的技术错误码集合，空集合禁止自动重试 |

GET /api/tasks 在已有 TaskDefinition 上叠加代码中的 metadata，不允许管理员通过数据库字段把高风险插件伪装成只读。
风险标记表达插件约定，不是 Python 沙箱。实际代码仍需检查和测试。
旧插件保留 retry_safe 兼容行为；新插件必须声明明确的 config_schema、metadata 和 retry_policy。

## Config Schema 与样板

BrowserProbeConfig 支持 url、selector（默认 h1）、expected_title、expected_text。
当前只允许 `http://127.0.0.1:<port>` 上的 `/simple`、`/form`、`/delay`、`/redirect`、`/error`、`/storage`；
拒绝凭据、query、fragment 和外部 URL。该地址相对于执行 Worker，不是浏览器管理页面所在的电脑。
服务必须是你控制的本地测试站点。这里不是任意 URL 的安全扫描器，未来放开站点须单独设计目的地和重定向访问策略。

完整的 BrowserReadOnlyProbeTask 实现：

```python
from typing import ClassVar

from app.tasks.plugins.probes.common import (
    BrowserProbeConfig, ProbeTask, browser_probe, success,
)
from app.tasks.registry import register_task


@register_task
class BrowserReadOnlyProbeTask(ProbeTask):
    task_code = "BROWSER_READONLY_PROBE"
    task_name = "浏览器只读诊断"
    config_schema = BrowserProbeConfig
    required_capabilities: ClassVar[dict[str, set[str]]] = {
        "browser": {"browser.navigation", "browser.text"},
    }
    timeout_seconds = 30

    async def execute(self, context):
        data, evidence = await browser_probe(context)
        return success(data, evidence)
```

`common.py` 中的 browser_probe 是三个样板共用的业务步骤：设阶段 BROWSER → 创建不恢复登录态的 Session → goto →
读取 title/selector → 比较预期 → 构造安全证据。它只使用 BrowserAdapter 接口，不调用 Playwright。
实际可运行源码见 `backend/app/tasks/plugins/probes/browser_readonly.py` 和 `common.py`，不要把示例重复注册进同一工程。
OneBotProbeConfig 是拒绝额外参数的空配置；登录身份取 TaskContext.account，不从配置覆盖。
Composite 使用 BrowserProbeConfig，先 OneBot 再 Browser，任何阶段失败即整体失败。

## TaskResult 与 Evidence

TaskResult 包含 success、status、message、error_code、data、evidence、failed_stage、retryable、task_version、plugin_version、
execution_id、started_at、ended_at。兼容保留 start_time/end_time；两种时间名称序列化值相同，由 Engine 统一赋值。
仅允许终态，success 必须与 SUCCESS 一致；data/evidence 递归拒绝敏感字段。
Worker/Service 将完整 JSON 保存到 TaskExecution.result_json，插件不写数据库。

Probe 只返回脱敏登录 ID（末四位）、身份校验布尔值、HTTP 状态和文本匹配结果。
Evidence 中 title 仅允许已知的 `Browser fixture`，其他动态标题替换为 `[REDACTED]`；不保存原始页面正文。
final_url 仅保留 origin，去掉路径、query 和 fragment。verification 保存 title/text/http 布尔值。
不得输出 Cookie、Token、Authorization、密码、storage_state、localStorage、sessionStorage、HTML、完整好友列表。
通用字段过滤不能理解自由文本里的任意秘密，插件必须像样板一样使用确定的输出白名单。

## 错误与阶段

- TaskConfigError → TASK_CONFIG_INVALID，发生在 Adapter 注入前。
- TaskPreconditionError → 账号/前置条件错误，例如 ONEBOT_ACCOUNT_MISMATCH。
- TaskVerificationError → TASK_VERIFICATION_FAILED，例如缺失文本、标题不符、HTTP 500；不是 BrowserError。
- TaskBusinessError → 其他明确业务失败。
- TaskUserActionRequired 或 BrowserUserActionRequired → NEED_USER_ACTION，不自动重试。
- AdapterError 由 Engine 统一转换，插件不逐个拼装异常 TaskResult。

用 context.set_stage("ONEBOT") / set_stage("BROWSER") 标记当前步骤，失败返回 failed_stage。
Probe 将旧节点提供器的 ONEBOT_IDENTITY_MISMATCH 统一映射为 ONEBOT_ACCOUNT_MISMATCH；旧插件错误码不变。
未绑定 Node 返回 NODE_NOT_CONFIGURED，未配置端点或凭据保留明确配置错误，不返回成功。
统一日志记录 execution_id、task_code、account_id、stage、status、duration；不记录异常原文或配置内容。

## Retry 与 Timeout

新的自动重试资格为：技术异常 retryable=true AND 插件 idempotent/read_only=true AND 错误在插件 retry_policy 中。
Engine 将资格写入 result.retryable；Dispatch 再检查白名单、插件当前策略及最大次数，使用既有新 execution + parent_execution_id 链。
不会修改失败父记录，也不会在插件里睡眠重试。业务失败、人工验证和整个 Task 超时均不自动重试。
OneBot Adapter 已耗尽短重试时设置 retryable=false；Browser Adapter 当前也为 false，所以两者不会被 Worker 再次放大重试。
Fake 的 transient 模式用于验证允许重试的技术错误路径。旧 builtin 的 retry_safe 策略继续兼容。

有效任务超时是 min(Task.timeout_seconds, Engine 全局上限)。当前 Compose 全局默认 30 秒，因此 Composite 声明 45 秒时仍受 30 秒上限约束。
修改全局配置需重新部署 Worker。外部非幂等写操作默认禁止自动重试，必须另行评估结果未知状态。

## Scheduler

Dispatch.schedule 跳过 scheduled=false 或 diagnostic_only=true 的任务，即使 TaskConfig.enabled=true。
Probe 只能通过现有手动执行/补执行入口运行，不新增诊断专用 API。

## 测试

FakeOneBotAdapter 复用标准 OneBot 类型转换，支持 success、offline、timeout、invalid、connection、api、transient。
FakeBrowserAdapter 支持 success、timeout、navigation_error、user_action；不启动真实 Chromium。

```sh
backend/.venv/bin/python -m pytest backend/tests/test_probe_tasks.py -q
backend/.venv/bin/python -m pytest backend/tests -q
PLAYWRIGHT_BROWSERS_PATH="$PWD/artifacts/playwright" backend/.venv/bin/python -m pytest backend/tests -m browser_integration -q
backend/.venv/bin/ruff check backend/app backend/tests backend/alembic scripts
```

真实用例 test_probe_integration.py 使用真实 Redis Stream、Worker.run、TaskEngine 和 Chromium，本地临时 SQLite 存储执行结果。
从现有 POST API 投递，GET execution 查询终态；分别验证 Browser 和 Fake OneBot + Real Browser Composite。
测试 Redis 使用随机前缀，清理自己的 key，不使用 FLUSHDB。普通 pytest 不访问 QQ。

真实 Docker + MySQL 验收：

```sh
docker compose up -d --build
backend/.venv/bin/python scripts/e2e_probe.py
```

工具需要恰好一个 Worker，临时站点只监听 Worker 容器的 loopback；退出时关闭站点。
通过管理 API 登记尚不存在的三个定义，创建临时 WEB 账号，执行 BROWSER_READONLY_PROBE，校验结果后软删除账号，保留执行审计。
读取本地 .env 管理凭据，不输出凭据；不调用 OneBot，不运行 QQ 写操作。

配置真实 NapCat 并完成 Phase 6.5 后，才执行：

```sh
REAL_ONEBOT_ACCOUNT_ID=1 backend/.venv/bin/python -m pytest backend/tests -m real_onebot_task -q
```

必须替换为本人账号 ID。此用例通过 Service 按 Account→Node 选择真实 Adapter，只运行只读 OneBot Probe，
不伪造数据库执行记录。当前状态为 REAL_ONEBOT_TASK_NOT_TESTED。

## Phase 8B-1 扩展：只读业务与账号摘要

四个 QQ 业务 Task 位于 `app/tasks/plugins/qq`，继承 QQReadOnlyTask，不继承 ProbeTask。
它们是 BUSINESS / QQ_ACCOUNT，diagnostic_only=false、scheduled=false；仍沿用相同 Config、Result 和错误边界。

QQReadOnlyTask 声明 onebot_worker_retry=true。Engine 只从受信任类元数据设置上下文，OneBot provider 用 ContextVar 隔离重试所有权。
该作用域内只读 RPC 不执行内部短重试，保留连接/超时错误的 retryable，Worker 按全局次数和退避处理。
写操作永远不由此机制获得重试资格。Probe 沿用原有 Adapter 内部重试模式；不要在 Task 中另加重试循环。

RuntimeAdapters.services_for_context 注入绑定 account_id/execution_id 的 AccountRuntimeReader。
Task 通过 `context.get_service("account_runtime").snapshot(hours)` 获取非敏感摘要，方法不接受其他账号 ID。
Repository 只 SELECT 当前账号、Node 状态和该账号最近成功/失败执行的少量列；不加载 result_json、凭据或完整历史。
相同结束时间使用内部记录顺序确定最新状态，内部排序字段不返回给 Task。

QQ_RUNTIME_STATUS 声明 onebot_status_only=true 且只要求 status capability。provider 注入 StatusOnlyAdapter，
只暴露 get_status，不预先要求在线登录，也不提供好友、群或登录身份接口。这样离线状态可被正常查询，但不能借此读取其他身份数据。
其他 QQ 任务仍执行 Node 登录身份校验。

业务错误别名统一为 ONEBOT_OFFLINE、ONEBOT_ACCOUNT_MISMATCH、ONEBOT_AUTH_FAILED；超时保留 ONEBOT_TIMEOUT。
好友/群 RPC 的日志只有关联字段、固定阶段名和 duration，不含列表内容。
