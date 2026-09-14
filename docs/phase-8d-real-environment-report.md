# Phase 8D：真实环境验证报告

日期：2026-09-14。本轮完成前置条件、基线与安全检查，**未完成真实环境验收**。

## Final Status

- Phase 8D：**WAITING_FOR_REAL_ENVIRONMENT**，不是 PASS，也不是 PARTIAL_COMPLETE。
- 8D-A：**WAITING_FOR_REAL_NAPCAT**。
- 8D-B：**WAITING_FOR_REAL_QQ_WEB_LOGIN**，同时缺少真实页面 URL 和真实 Selector Profile。
- **PRODUCTION_AVAILABLE_OPERATION_COUNT = 0**。
- REAL_ENV_VERIFIED Operation 列表：**空**。

两块独立等待，任何一块具备条件后可单独推进。本轮没有自动安装/启动 NapCat、自动登录 QQ、生成真实 Token、访问猜测 URL 或执行 QQ 写操作。

## Baseline

已阅读 AGENTS、README、Phase 6/6.5/7/8B-1/8B-2/8C 报告及 Router 文档和能力矩阵。

| 检查 | 本轮结果 |
| --- | --- |
| 普通 pytest | **495 passed, 49 skipped**，9.59 秒 |
| Ruff | All checks passed |
| Alembic check | No new upgrade operations detected |
| Docker | 六个常驻服务 running / healthy |
| Chromium | 上阶段已验证 43 passed；本轮未重跑，未修改运行代码 |

本轮仍有两条已有 Starlette/httpx/AnyIO 弃用提示。没有修改依赖或降低校验规则。

基线和预检结果保存在默认忽略的 `artifacts/phase-8d/preflight-summary.json`，宿主和容器分别为 `host-preflight.json`、`backend-preflight.json`。仅记录配置存在性、数量和固定状态，不含凭据或真实页面内容。

## NapCat Environment

分别检查宿主 Settings 和运行中 backend 容器 Settings，结果一致：

- OneBot Node 数量：0。
- HTTP Endpoint：未配置。
- WS Endpoint：未配置。
- 全局 OneBot 凭据：未配置。
- Node 凭据引用映射：未配置。
- 因没有 Node，不存在可用于验证的 Node→Account 绑定。
- 运行中的 Docker 容器只有本项目六个常驻服务，没有 NapCat 容器。

这些事实只说明没有可供项目验证的已配置实例，不断言用户电脑其他位置绝对未安装 NapCat。

## NapCat Version

NOT_TESTED。未获得真实 NapCat 或 OneBot 版本响应。

## OneBot HTTP

运行已有 `python -m app.tools.onebot_diagnose`，实际返回：

```json
{
  "overall": "WAITING_FOR_REAL_NAPCAT",
  "real_status": "REAL_NAPCAT_NOT_TESTED",
  "onebot_node_count": 0
}
```

退出码 2 表示等待，不是诊断通过。health、version、status、login、friend、group 均 NOT_TESTED，没有真实响应耗时或身份匹配证据。

## OneBot WS

connect/auth/heartbeat/meta_event/disconnect/reconnect 全部 NOT_TESTED。没有停止任何外部 NapCat 进程，也没有通过消息制造事件。

六服务 healthy 只能证明当前平台健康，不能替代 NapCat 停启隔离验收。

## OneBot Business Tasks

QQ_ACCOUNT_STATUS、QQ_FRIEND_SUMMARY、QQ_GROUP_SUMMARY、QQ_RUNTIME_STATUS 的真实完整链路均 NOT_TESTED。

旧业务真实测试目前直接使用 TaskEngine/OneBotService，尚不构成 Phase 8D 要求的 Router 全链路证据。本轮没有运行该路径访问真实账号，也没有把历史 Mock 通过作为真实证据。

四项旧 Task 的 Router 迁移、受控真实验证入口与证据登记尚未完成。具备环境后，必须先完成这项接入再执行真实业务验收；不能先全局标记 REAL_ENV_VERIFIED 来让 Router 放行，也不能绕过 Router 验收后宣称链路完整。真实操作只允许受控只读验证，验证成功再逐项登记最终证据。

## QQ Web Environment

宿主与 backend 容器均：

- QQ_WEB_BASE_URL：空。
- QQ_TASK_CENTER_URL：空。
- QQ_ACTIVITY_URL：空。
- 现有 Browser 加密密钥已配置，但加密 State 文件数量：0。

没有已确认真实页面或人工登录态，不能开始真实页面探索。不使用浏览器历史中的 localhost 文档页或 Fixture 作为 QQ URL。

## QQ Web Login

**WAITING_FOR_REAL_QQ_WEB_LOGIN**。没有自动扫码、输入账号密码、识别验证码或处理设备确认。未创建明文 State，没有登录截图。

## Task Center

REAL_QQ_WEB_NOT_TESTED。真实 total/completed/pending/claimable 及 items 均未读取，不能返回伪造的零任务结果。

## Activity Center

REAL_QQ_WEB_NOT_TESTED。真实活动数量、可用数量均未读取。

## Selector Profile

Fixture Selector 保持不变。没有真实页面证据，因此没有虚构 RealSelectorProfile、page_signature、verified_at 或页面版本。

受控 Site Inspection / Diagnostic Mode、真实 Selector 校准及 real_qq_web 测试用例尚未完成；需要真实目标后才能形成可验证的读取和脱敏规则。后续必须保留 Fixture 回归，真实 Profile 独立登记；截图默认关闭，不保存完整 HTML 或 QR。

## Capability Upgrades

本轮没有等级升级，也没有修改 Operation 登记或优先级。

- REAL_ENV_VERIFIED：Chromium 基础设施；**业务 Operation 无**。
- FIXTURE_VERIFIED：QQ_WEB_LOGIN_STATUS_READ、QQ_WEB_PAGE_STATUS_READ、QQ_TASK_CENTER_READ、QQ_ACTIVITY_READ。
- MOCK_ONLY：QQ_ACCOUNT_STATUS_READ、QQ_FRIEND_SUMMARY_READ、QQ_GROUP_SUMMARY_READ、QQ_RUNTIME_STATUS_READ。
- NOT_VERIFIED：真实 QQ Web、真实 Mobile，以及 QQ_DAILY_CHECKIN、QQ_ACTIVITY_CLAIM、QQ_FEED_BROWSE、QQ_VIDEO_TASK、QQ_NOVEL_TASK、QQ_GAME_TASK、QQ_QZONE_PUBLISH、QQ_ADD_FRIEND。

真实 NapCat 仍 REAL_NAPCAT_NOT_TESTED。Mobile 仍 NOT_CONFIGURED。

没有真实验证成功，故不生成伪造的 Capability Evidence。后续必须按 Operation+Executor 记录真实时间、版本、环境和证据来源，不能由单次 login_info 成功升级全部业务。

## Production Operations

**PRODUCTION_AVAILABLE_OPERATION_COUNT = 0**，可执行 Operation 列表为空。受信任登记表中没有 REAL_ENV_VERIFIED 的 QQ 业务，当前环境也没有可用的真实节点或登录态。

## Tests

| 类型 | 本轮结果 | 含义 |
| --- | --- | --- |
| 普通 pytest | 495 passed / 49 skipped | 基线稳定 |
| `-m real_onebot` | 1 skipped / 543 deselected | 缺少真实记录 ID，实际执行 0 项 |
| `-m real_onebot_business` | 4 skipped / 540 deselected | 缺少真实账号，实际执行 0 项；旧测试不替代 Router 验收 |
| `-m real_qq_web --collect-only` | 0 项，544 deselected，退出码 5 | 尚无该真实用例，不是 PASS |
| Ruff | PASS | 源码、测试、迁移和脚本扫描通过 |

real_qq_web 专用 marker/安全收集门禁尚未接入。没有用恒定 skip 的空壳测试包装成已实现真实验证。后续加入用例时必须先确保普通 pytest 即使带有真实环境变量也不会访问 QQ。

## Security Check

- 扫描当前 198 个源码、测试、迁移、文档、脚本和项目配置文件：已配置真实凭据的精确匹配文件数量为 0。
- `.env` 文件权限为 0600，未修改实际凭据或登录态。
- `.gitignore` 已包含 `.env`、`artifacts/`、`playwright/.auth/`、`*.state.enc`。
- 本轮诊断 artifact 只含布尔值、数量和固定状态，位于已忽略 artifacts 目录。
- 已执行 git status / git diff，但目录不是 Git 仓库。**无法审计索引、diff 或历史提交，不宣称 Git 历史无凭据。**
- 精确匹配扫描只能证明本轮检查范围内未发现当前已知凭据，不能替代所有形式的 Secret 审计。

没有保存完整好友/群列表、HTML、Cookie、Storage 内容、QR 或个人消息。

## Failures

没有真实请求失败证据；当前是前置条件不满足。Git 检查不可用，real_qq_web 无测试被选中，这两项明确记录，未改写为成功。

## Waiting Items

### 8D-A 用户准备

1. 启动已有或自行配置的 NapCat，并由本人完成 QQ 登录与必要验证。
2. 开启 OneBot HTTP、正向 WS 和 heartbeat，确保平台容器可达。
3. 在本地 `.env` 中配置凭据映射，不发送 Token 到聊天。
4. 通过管理 API 登记 ONEBOT Node 的 HTTP/WS 和 secret_ref，绑定本人 QQ Account。准备实际 Node ID、Account ID。

已有步骤见 [Phase 6.5 用户操作说明](phase-6.5-real-napcat-report.md#用户下一步操作)。不要把 WebUI 管理端口当作 OneBot HTTP 端口。

完成后先运行已有只读诊断（将占位符替换成实际 ID）：

```sh
docker compose exec -T backend python -m app.tools.onebot_diagnose --node-id <NODE_ID> --account-id <ACCOUNT_ID>
```

该命令只是前置诊断。身份、鉴权、WS 和停启恢复通过后，还需接入 Router 并完成四项业务的实际链路，才能升级对应 Operation。

### 8D-B 用户准备

1. 提供来自实际页面的 QQ Web 登录/个人页、任务中心、活动中心 URL，不含凭据或敏感查询参数。
2. 明确要验证的 Account ID，由本人完成登录和验证。
3. 在受控账号 Context 中保存加密 State，不把明文 State、Cookie 或二维码发到聊天。

本项目尚未提供完成此次真实页面人工登录采集的入口，不宣称已有一键导入流程。目标确认后再接入受控人工登录保存及页面检查，保留现有导航边界，不让业务参数接收任意 URL。

## 修改文件 / 数据库 / API

本轮仅新增本报告、更新 README 和能力矩阵的 8D 状态，并保存忽略目录内的脱敏预检结果。没有业务代码、数据库结构、API、TaskDefinition 或验证等级变更。

**Phase 8D 尚未完成；两块环境可独立补齐后继续。本轮不自动决定或实施后续阶段。**
