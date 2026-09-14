# Phase 7：Playwright Browser Adapter 验收报告

日期：2026-09-11。Phase 6.5 继续为 WAITING_FOR_REAL_NAPCAT；本阶段仅验证本地 Chromium 基础设施。

## 完成内容

实现 BrowserAdapter、BrowserManager、BrowserSession、BrowserPage、StorageProvider、统一异常和 FakeBrowserAdapter。
接入 Worker 和本地 task_engine 生命周期，提供本地诊断服务、18 项真实 Chromium 集成测试及独立普通测试。
没有实现 QQ 业务插件、Vue、验证码识别、设备验证绕过、stealth 或反检测功能。

## Browser 架构

```text
Task → AdapterRegistry → ScopedBrowserAdapter（绑定本次账号/执行）
                     → BrowserAdapter → BrowserManager
                                      → BrowserSession → BrowserPage → Playwright async API
                                      → StorageProvider → EncryptedFileStorage
```

BrowserManager 负责一个 Worker 内的一份 Chromium 与 Playwright driver。
Session 只拥有一个独立 BrowserContext；Page 包装高频 API，Task 不接触 raw Page / Context 或启停 Browser。
SiteAdapter Protocol 预留网站认证规则，未实现任何 QQ SiteAdapter。

## 生命周期

startup 并发安全、可重复调用；shutdown 幂等并按 Context → Browser → Playwright 关闭。
Context 创建异常和取消时释放 semaphore；Session.close 在异常和超时下也释放容量。
任务作用域关闭全部已创建 Session，即使其中一个关闭失败也尝试其他 Session。
作用域结束后拒绝再次创建 Session。Manager 不自动重放任务或页面动作。

## Session 隔离

Session 包含 account_id、session_id、created_at、last_used_at 和内部 Context。
每次创建使用独立 Context，Worker 的 ScopedBrowserAdapter 禁止指定其他账号。
真实 Chromium 已验证账号 A/B 的 Cookie、localStorage、sessionStorage 分离；A 状态恢复不污染 B。
BROWSER_MAX_CONTEXTS 使用 semaphore，达到上限后等待；任务超时或取消可中断等待。

## Storage State

StorageProvider 提供异步 load / save / delete，当前实现受控本地 Fernet 认证加密文件。
密钥从 Settings.browser_storage_key / .env 注入；新部署初始化脚本自动生成。现有 .env 只新增密钥，没有输出或覆盖其他配置。
密文包含 account_id 校验，交换不同账号文件会失败。目录 0700，文件 0600，写入使用临时密文文件 + fsync + 原子替换。
不生成明文状态文件，不写入数据库；损坏、密钥错误、文件访问失败均为 BrowserStorageError。
恢复支持 Cookie、localStorage、IndexedDB；sessionStorage 不属于 Playwright storage_state，未宣称恢复。
同账号并发保存采用最后成功写入者；本阶段没有跨 Worker 的账号状态合并或账号级会话锁。

## BrowserPage 与证据

实现 goto / click / fill / text / exists / wait_for / wait_for_url / evaluate / reload / screenshot / close。
支持 CSS、text、role；不存在的 selector 可用 exists 返回 false，HTTP 500 导航返回状态码，不把站点业务失败误判为浏览器故障。
NavigationTimeout / ActionTimeout / SelectorTimeout 分别映射统一 BrowserTimeoutError 子类。

截图默认 FAILURE_ONLY，必须显式传 failure=True 和 safe_selector；只拍选定区域，输入字段等强制遮罩。
DISABLED 禁止截图。文件名使用清理后的执行 ID、任务 code 和随机 UUID，避免覆盖和路径穿越。
通用层不能保证判断任意页面文字是否敏感，站点插件需明确声明安全区域，否则不截图。
TaskContext.record_browser_evidence 收集类型化证据进入既有 result_json 的 data.browser_evidence。
URL 仅保存 origin，不保存动态标题、Cookie、Storage 或 Authorization。

## Capability

沿用按 Adapter 分组的 required_capabilities：

```python
required_capabilities = {"browser": {"browser.navigation", "browser.click", "browser.storage_state"}}
```

已提供 browser.navigation、click、fill、text、wait、screenshot、storage_state、evaluate。
TaskEngine 执行插件前检查能力。网站主动声明 BrowserUserActionRequired 后统一返回 NEED_USER_ACTION，等待本人处理。
Browser 本身不猜测验证码或登录页。FakeBrowserAdapter 模拟成功、超时、导航失败和验证挑战，不启动真实浏览器。

## Worker 集成

RuntimeAdapters 同时管理按节点注入的 OneBot 与每进程 Browser。
Worker 启动 Browser，退出时无论清理是否失败都会尝试关闭 OneBot、Redis、数据库资源。
Browser 启动失败只降低 Browser 可用性，不阻止 Worker 接收其他 Adapter 的任务。
Worker 心跳新增 browser 字段；系统健康增加可选 browser 汇总，不改变核心数据库/Redis 的健康判定。

真实 Chromium 集成测试直接运行 Worker 的退出等待逻辑，确认它等待本地浏览器任务完成并关闭 Context。
Docker 对空闲但持有浏览器进程的 Worker 进行了 SIGTERM 与 SIGKILL 实测，结果见 Docker 节。

## 异常与重试

BrowserError 继承通用 AdapterError，提供 error_code / message / retryable。
覆盖 Start、Closed、Session、Navigation、Action、Timeout、Storage、PageCrash、UserActionRequired。
底层异常文本、selector、fill 内容、evaluate 脚本不写日志。
当前浏览器层不做自动重试，所有浏览器错误 retryable=false；Worker 自动重试白名单没有 BROWSER_*。
后续若增加启动瞬时重试，只能围绕启动过程，不能自动重放 click、submit、发送或发布。

## 数据库与 API

无新增表、字段或 Alembic Migration。任务证据使用既有 TaskExecution.result_json。
GET /api/system/health 新增 browser: UP / DEGRADED / DOWN；GET /api/system/worker-status 每条心跳新增 browser。
API 进程不会为健康检查启动浏览器，没有公开 URL 自动访问、evaluate、Cookie 导出或截图接口。

## Docker

安装 Playwright Chromium 和 Linux 依赖，未安装 Firefox/WebKit。
使用非 root platform 用户、PLAYWRIGHT_BROWSERS_PATH=/ms-playwright；Worker init=true，shm_size=256mb。
Browser 状态/截图使用 browser_data 命名卷，默认停止宽限期增加到 60s。
镜像 inspect Size 为 588616963 bytes（验收构建），后续代码层小幅变化会影响实际数字；首次下载和构建成本高于 Phase 6。

实测记录：

- docker compose build backend：通过；六个常驻服务 healthy，migrate Exited(0)。
- 容器内 browser_diagnose：startup / context / navigation / fill / click / storage / account_isolation / shutdown 全部 PASS。
- 正常 SIGTERM：Worker Exited(0)，没有改变其他服务状态；恢复启动成功。
- Worker 持有五个 headless_shell 进程时，向主 Python 进程发送 SIGKILL。
- Docker 自动重启，RestartCount 从 0 到 1，init=true。重启前 VM PID 为 33215/33217/33218/33234/33236；重启后为 34801/34803/34804/34818/34820。
- 新容器进程组恢复为一份 driver 和五个浏览器进程，没有不断增加；依赖 PID namespace / init 退出回收整组子进程。
- 该记录验证 Docker 模式，不宣称宿主裸进程 SIGKILL 也能执行清理；生产任务应使用容器。

## 修改文件

| 范围 | 文件（相对项目根目录） |
| --- | --- |
| Browser 实现 | backend/app/adapters/browser/{base,adapter,manager,session,page,schemas,exceptions,operations,storage,fake,__init__}.py |
| Adapter 生命周期 | backend/app/services/runtime_adapters.py、backend/app/tasks/bootstrap.py |
| 任务结果与上下文 | backend/app/tasks/base.py、engine.py |
| Worker / 健康 | backend/app/workers/worker.py、heartbeat.py、backend/app/services/system_service.py、schemas/system.py、main.py |
| 配置 / 日志 | backend/app/core/config.py、logging.py、.env.example、.gitignore、scripts/init_env.py |
| 本地诊断 | backend/app/tools/browser_site.py、browser_diagnose.py |
| 测试 | backend/tests/test_browser_unit.py、test_browser_integration.py、conftest.py、test_task_engine.py、test_foundation.py |
| 依赖 / Docker | backend/pyproject.toml、requirements.lock、Dockerfile、docker-compose.yml |
| 文档 | README.md、docs/phase-7-report.md、docs/phase-6.5-real-napcat-report.md（更新独立推进说明） |

## 测试结果

基线：217 passed、1 skipped；Ruff 和原六个容器健康通过。
最终普通测试与集成结果：

```sh
backend/.venv/bin/python -m pytest backend/tests -q
PLAYWRIGHT_BROWSERS_PATH="$PWD/artifacts/playwright" backend/.venv/bin/python -m pytest backend/tests -m browser_integration -q
backend/.venv/bin/ruff check backend/app backend/tests backend/alembic scripts
docker compose exec -T backend python -m app.tools.browser_diagnose
```

普通测试：250 passed、19 skipped（18 项 Chromium 重型测试 + 1 项真实 NapCat）。
真实 Chromium：18 passed；两组累计 268 项通过。原有 217 项全部保留并通过。
两项 warning 为既有 Starlette 测试依赖弃用提示。Ruff：All checks passed。
本地和 Docker Browser diagnose 均为 Overall PASS。

## Chromium 真实联调

实际版本：Playwright 1.62.0，Chromium/Chrome Headless Shell 151.0.7922.34（Playwright build v1234）。
macOS arm64 真实集成通过；Linux arm64 Docker 诊断通过。
真实测试使用 loopback /simple、/form、/delay、/redirect、/error、/storage，不访问外部业务站点。
覆盖启动/重复启停、goto、CSS/text/role、click、fill、wait、超时、redirect、reload、截图、状态保存恢复、
账号隔离、并发限制、Page close、真实 Browser.crash / Page.crash、认证 predicate 和 Worker 任务回收。
受限 macOS 沙箱最初不允许 Chromium 启动；在获准启动浏览器的宿主进程中通过，不把该限制伪装为测试成功。

## 安全与已知限制

- .env、artifacts/、*.state.enc、playwright/.auth/ 均被 Git 忽略；源码不含真实密钥。
- 当前目录尚未初始化 Git，不能声称审查了提交历史；使用当前环境密钥精确匹配扫描源文件、测试与文档。
- 本地存储不等同于 KMS；密钥丢失不能恢复状态，尚无自动轮换或跨主机共享状态服务。
- sessionStorage 不持久化；同账号并发状态不合并。
- 只运行可信 Python 插件；包装类不是 Python 插件代码的安全沙箱。evaluate / cookies 为内部基础能力，调用者必须保护返回数据。
- 截图需明确安全区域，不能自动识别所有敏感页面文字。完整标题默认不持久化。
- Docker 的 Chromium 使用 Playwright 默认启动设置；面向不受信任站点的 OS sandbox/seccomp、网络出口限制和资源配额需在 Phase 10 部署硬化时完成。
- Browser 健康依赖 Worker 心跳 TTL，故障到汇总变化可能有心跳周期延迟。崩溃后不自动重放业务，重启 Worker 或显式 startup 恢复。
- Phase 6.5 真实 NapCat 仍未验证；Phase 8 业务插件、Phase 9 Vue、Phase 10 压测与完整部署未实现。

参考：[Playwright 浏览器安装](https://playwright.dev/python/docs/browsers)、[状态保存](https://playwright.dev/python/docs/auth)、
[Docker 运行说明](https://playwright.dev/python/docs/docker)、[Fernet](https://cryptography.io/en/latest/fernet/)。
