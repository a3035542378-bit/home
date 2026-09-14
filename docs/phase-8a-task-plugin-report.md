# Phase 8A：Task Plugin 标准与只读样板验收报告

日期：2026-09-11。结论：**Phase 8A 完成**。Phase 6.5 仍为 WAITING_FOR_REAL_NAPCAT；真实 OneBot Task 明确为 REAL_ONEBOT_TASK_NOT_TESTED。

## 完成内容

建立类型化配置、结构化结果、插件 metadata、阶段错误、版本审计和安全重试契约。
新增 ONEBOT_READONLY_PROBE、BROWSER_READONLY_PROBE、COMPOSITE_PROBE，均为只读诊断任务。
没有开发真实 QQ 写任务、签到、Vue、验证码处理、风控绕过或浏览器伪装。

## Task Plugin 标准

Task → TaskContext / AdapterRegistry → Adapter。插件不导入 SQLAlchemy、Redis、httpx、requests、Playwright，也不直接写 Execution。
Engine 先校验配置，再注入 Adapter 和检查 capability，最后执行、验证 TaskResult。
统一在 execute 内完成前置检查、动作和验证；没有新增复杂生命周期钩子。Session 上下文及 RuntimeAdapters 负责清理。
固定受信任包 `app.tasks.plugins` 递归发现模块；新增任务只需建文件、继承、装饰器注册，无需修改 Engine 或 __init__ 清单。
数据库 TaskDefinition 仍通过现有管理 API 登记。

## Task Metadata / Risk Level

Probe 的 idempotent/read_only/diagnostic_only=true，scheduled=false，side_effect_level=NONE，risk_level=SAFE_READONLY。
定义 TaskRiskLevel，预留 LOW_SIDE_EFFECT 和 HIGH_SIDE_EFFECT。风险声明不是运行时沙箱。
TaskDefinition 返回任务类型、类别、能力、风险、诊断标记、版本、超时和 retry_policy，由插件代码提供，无迁移。
每次执行由 Engine 记录 task_version=1.0.0、plugin_version=1.0.0，避免插件自行漏记版本。
旧 builtin 和 retry_safe 路径继续兼容。

## Config Schema

OneBotProbeConfig 为禁止额外字段的空配置；身份只取 AccountContext。
BrowserProbeConfig / Composite：url、selector、expected_title、expected_text。
目前限定 Worker 本机 `127.0.0.1` 的受控 HTTP 测试页面路径，禁止外部地址、URL 凭据、query 和 fragment。
校验失败返回 FAILED / TASK_CONFIG_INVALID，provider 不会被调用；不把原始 ValidationError 写入日志。

## Error Model

TaskConfigError、TaskPreconditionError、TaskVerificationError、TaskBusinessError、TaskUserActionRequired。
AdapterError 保持由 Engine 转换；人工验证统一 NEED_USER_ACTION。
OneBot 账号不匹配统一 ONEBOT_ACCOUNT_MISMATCH，包括旧 Node provider 的错误别名映射，旧插件错误码不受影响。
未配置 Node 返回 NODE_NOT_CONFIGURED，不伪造成功。
Composite 记录 failed_stage=ONEBOT/BROWSER；无效配置为 CONFIG。预期文本不存在、标题不符、HTTP 500 都属于业务验证失败。

## TaskResult / Evidence

新增 evidence、failed_stage、retryable、task_version、plugin_version、started_at、ended_at；start_time/end_time 兼容保留。
结果由 Worker/Service 保存到已有 TaskExecution.result_json。
只读结果包含脱敏登录 ID、身份校验、HTTP 状态、文本存在标记；Evidence 保存已知测试标题、origin 和 title/text/http 验证布尔值。
动态标题除已知 Browser fixture 外一律脱敏；不保存任意文本、HTML、好友列表或浏览器状态。
data/evidence 递归拒绝密码、Cookie、Token、Authorization、storage_state、localStorage 等敏感键。
结构化日志增加 stage/duration，与 execution_id、account_id、task_code、status 共同输出，不记录自由文本或异常输入。

## Retry Model / Timeout

新插件必须同时满足 AdapterError.retryable、插件 idempotent/read_only、插件错误码策略；Engine 输出最终 retryable。
Dispatch 再检查当前 metadata、持久化结果和全局次数，继续创建新的 RETRY execution，parent_execution_id 指向原 FAILED 记录。
测试证明父记录不改变，业务失败、OneBot 已耗尽重试、NEED_USER_ACTION、任务整体超时不自动重试。
当前 OneBot 耗尽内部预算和 Browser 技术错误都为 retryable=false，不进行叠加重试。
Fake transient 仅用于验证允许自动重试的技术错误场景。

声明超时 OneBot=10s、Browser=30s、Composite=45s，实际采用 min(插件声明, Engine 上限)。当前 Compose 默认上限 30s。
所有重试排队仍通过原 Outbox.available_at，不在插件内睡眠或自行修改执行记录。

## Worker / Scheduler / API

复用现有 POST /api/tasks/{task_code}/execute，返回 202。任务在真实 Redis Stream 中消费，经 Engine 和 Adapter 执行，再 GET execution 查询。
不增加特殊 Probe API。Dispatch.schedule 明确排除 diagnostic_only=true 或 scheduled=false，已通过持久层测试。
真实 Docker 验收登记三个定义，创建临时 WEB 账号，执行 Browser Probe，成功后软删除账号、关闭临时站点，保留执行审计。

## 数据库变化

无新增表、列或 Migration，Alembic check：No new upgrade operations detected。
新增三个 TaskDefinition 数据记录，元数据从当前插件代码叠加；execution.result_json 保存本次版本、证据和重试判定快照。
诊断账号采用软删除，执行记录保留。

## 测试结果

基线复验：250 passed、19 skipped，Ruff 通过，六个常驻服务 healthy。

| 检查 | 最终结果 |
| --- | --- |
| 普通 pytest 全量（含完整 Task Engine / DB 回归） | **293 passed、22 skipped** |
| 显式 browser_integration | **20 passed、295 deselected** |
| 两组累计通过 | **313 项**，总收集 315 项，仅两项真实 OneBot 尚未执行 |
| Ruff | All checks passed |
| docker compose config --quiet | 通过 |
| Alembic check | 无新迁移操作 |
| Docker build backend | 通过，Chromium 层复用 |
| Docker 六个常驻容器 | healthy |
| 真实 Docker API → Redis → Worker → Browser → MySQL | **PASS** |
| Real OneBot Task | **REAL_ONEBOT_TASK_NOT_TESTED** |

22 项默认跳过 = 20 项 Chromium + 1 项 Phase 6.5 real_onebot + 1 项 real_onebot_task。
较 Phase 7 新增 43 项普通测试、2 项真实 Browser Probe 集成测试、1 项显式真实 OneBot Task 用例。
保留两项既有 Starlette/AnyIO 测试依赖弃用警告。

实现期间完整回归发现 FakeOneBotAdapter 兼容接口问题，已恢复并扩展原 Fake，原节点/诊断测试全部通过。
真实测试发现旧 action timeout 测试把创建页面也限定为 150ms，已将短超时设置移到页面准备后，整组复验通过。
这些失败没有计入通过结果。

## 真实 Browser Task 联调

自动化测试覆盖两条完整链路：

1. HTTP ASGI API → 真 Redis Stream → Worker.run → TaskEngine → BrowserReadOnlyProbe → 真 Chromium → 临时 SQLite Execution。
2. 同一链路执行 CompositeProbe，使用 Fake OneBot + 真 Chromium，验证两个 Adapter 组合与 Session 回收。

另外已对最终镜像运行实际 HTTP / Docker / MySQL 验收：

```sh
backend/.venv/bin/python scripts/e2e_probe.py
```

最新成功 execution_id：`bdffda52-9f2f-4366-94c3-dc7e52fc1f05`。
worker_id：`51f06393ef2a-7-c2d28dfc`。终态 SUCCESS。

```json
{
  "title": "Browser fixture",
  "final_url": "http://127.0.0.1:34967",
  "verification": {"http": true, "text": true, "title": true}
}
```

该端口是临时测试站点，验收后已关闭，不能作为长期配置复用。
真实测试版本沿用 Playwright 1.62.0 / Chromium 151.0.7922.34；宿主 macOS arm64 与 Docker Linux arm64 均通过。
未依赖外部网站，未执行任何 QQ 请求或写操作。

## 修改文件

| 范围 | 文件（相对项目根） |
| --- | --- |
| 插件 | backend/app/tasks/plugins/__init__.py、probes/{__init__,common,onebot_readonly,browser_readonly,composite_probe}.py |
| Engine / 契约 | backend/app/tasks/{base,errors,engine,registry}.py |
| 调度 / 管理 | backend/app/services/{dispatch,management}.py、backend/app/schemas/management.py |
| Adapter | backend/app/adapters/browser/{page,fake}.py、backend/app/adapters/{errors,onebot/fake}.py |
| 安全 / 日志 | backend/app/core/{security,logging}.py |
| 验收工具 | backend/app/tools/probe_site.py、scripts/e2e_probe.py |
| 测试 | backend/tests/{test_probe_tasks,test_probe_integration,test_real_onebot_task,test_browser_integration,conftest}.py |
| 测试 marker | backend/pyproject.toml（无依赖变化） |
| 文档 | README.md、docs/task-plugin-development.md、docs/phase-8a-task-plugin-report.md |

本阶段未修改 Dockerfile/Compose 架构，已重新构建并部署当前源代码。未初始化 Git，不能声称已有提交或历史审计。
源文件/测试/文档已检查当前管理密钥与浏览器密钥精确匹配，无泄露；.env 权限保持 0600。

## 已知限制与尚未完成

- 真实 NapCat 尚未配置，Phase 6.5 与 Real OneBot Task 均未验收；Real OneBot + Real Browser 组合也未执行。
- Browser Probe 只开放受控本机测试路径，任意外部网站、重定向访问控制和网站认证规则不在本阶段。
- 只保存固定测试标题与验证结果，不提供任意正文抓取；敏感字段过滤不能替代插件输出白名单。
- metadata 来自当前代码，历史执行保存版本号和结果，没有单独保存完整历史插件清单。
- TaskConfig 在 Worker 领取时读取，仍沿用已有配置语义，未新增投递时配置快照。
- Docker e2e 工具限定一个 Worker，避免本机临时站点与多 Worker 路由不一致；平台多 Worker 能力不变。
- 全局任务超时可小于插件声明值；旧 builtin 保留旧 retry_safe 兼容分支，新插件应使用完整 metadata。
- Phase 8B 真实业务任务、Phase 9 Vue、Phase 10 部署硬化/压测尚未实施。

## 2026-09-14 重复需求复验

本次附件与既有 Phase 8A 要求一致，保留现有实现，无业务代码、API 或数据库结构修改。
最初 Docker daemon 未启动，Redis 不可达，普通测试出现 32 项环境错误，Chromium 的两项队列测试也无法初始化。
已启动 Docker Desktop 并执行 `docker compose up -d --no-build` 恢复服务，保留数据卷，随后重新验证：

- 普通 pytest：293 passed、22 skipped，2 项既有依赖弃用警告。
- 真实 Chromium：20 passed、295 deselected，包含两个 Probe 队列集成用例。
- Ruff 与 Compose 配置校验通过。
- 六个常驻容器 healthy，系统 api=UP、database=ok、redis=ok、browser=UP。
- 实际 Docker API → Redis → Worker → Browser Probe → MySQL：PASS。
- 本次 execution_id：`e709189c-f830-442e-82c8-14da984677fb`，终态 SUCCESS。
- 结果包含已知标题、临时站点 origin、三项验证布尔值及版本 1.0.0；验收工具清理临时账号并保留执行审计。
- 本次复用已有镜像，没有重新构建；真实 OneBot 仍为 REAL_ONEBOT_TASK_NOT_TESTED。

Phase 8A 复验通过，未推进 Phase 8B。
