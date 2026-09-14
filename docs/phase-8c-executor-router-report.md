# Phase 8C：Executor Router 与 Capability Matrix 验收报告

日期：2026-09-14。

## 完成内容

完成 Operation、Executor 类型、CapabilityResolver、ExecutorRouter、VerificationLevel、RiskPolicy、Mobile 接口/Fake、Capability API 与能力矩阵。没有新增业务执行，没有任何写操作任务，没有修改 TaskEngine、Repository 或旧 Task。

开始前复验：406 passed / 49 skipped；Ruff、Alembic、六个 Docker 服务健康状态均通过。

## Operation 模型

共 16 个 OperationCode：八个现有读操作和八个保留操作。包含 code、read_only、idempotent、risk_level、side_effect_level、allowed_executors、所需能力及 implemented。

已有读操作为账号状态、好友摘要、群摘要、运行状态、Web 登录状态、Web 页面状态、任务中心摘要、活动摘要。预留签到、活动领取、动态浏览、视频、小说、游戏、空间发布、加好友；全部未实现，未知副作用按 HIGH_SIDE_EFFECT 保守处理。

## Executor 类型

ONEBOT、BROWSER、MOBILE、NONE。候选只来自 Operation 白名单，未选择返回 selected_executor=null。不同 Operation 独立登记顺序，可由 EXECUTOR_PRIORITIES 配置覆盖，不能靠配置改变验证等级或扩大白名单。

## Capability Resolver

返回统一 CapabilityResolution。综合账号状态、Adapter 能力、Node 健康和更新时间、Worker Browser 状态、State 可读性、对应站点配置、验证证据及风险策略。

候选同时提供 status 和 runtime_status：前者是综合结论，后者保留缺少配置、缺少认证或降级等运行事实。未经过真实业务验证的已实现操作显示 NOT_VERIFIED；不能把 Fixture 或健康状态当作生产放行依据。

State 内容读取后丢弃；State 存在不等于 authenticated。API 不访问 NapCat、不打开浏览器页面、不进行自动登录。

## Executor Router

实现 resolve、内部 require 和显式 resolve_fallback 框架，没有 execute。TaskContext 新增账号绑定的 executor_router 服务入口；拒绝使用其他账号上下文。

白名单/能力/运行状态/验证等级/风险条件满足后才按配置顺序选择。明确指定执行器时不会默默使用另一执行器。未知 Operation、非法执行器或模式使用统一错误。

## Verification Level

| 等级 | 当前证据 |
| --- | --- |
| REAL_ENV_VERIFIED | Chromium 基础设施；无 QQ 业务 Operation |
| FIXTURE_VERIFIED | QQ_WEB_LOGIN_STATUS_READ、QQ_WEB_PAGE_STATUS_READ、QQ_TASK_CENTER_READ、QQ_ACTIVITY_READ |
| MOCK_ONLY | QQ_ACCOUNT_STATUS_READ、QQ_FRIEND_SUMMARY_READ、QQ_GROUP_SUMMARY_READ、QQ_RUNTIME_STATUS_READ |
| NOT_VERIFIED | 真实 QQ Web、真实 Mobile，以及八项保留 Operation |

真实 NapCat 状态仍为 REAL_NAPCAT_NOT_TESTED。QQ Web 真实业务仍为 REAL_QQ_WEB_NOT_TESTED。静态受信任登记表没有通过环境变量或 API 升级验证等级的入口。

PRODUCTION 和 DIAGNOSTIC 都不允许选择未真实验证的候选；诊断模式只是展示，不提供执行绕过。

## Risk Policy

沿用已有 TaskRiskLevel 枚举。只允许 SAFE_READONLY 且 read_only/idempotent 都为 true 的已验证、已就绪候选。LOW_SIDE_EFFECT 本阶段不开放。HIGH_SIDE_EFFECT 即使明确指定执行器也不执行，不自动选择或 fallback。

## Fallback

默认关闭，只解析下一候选，不执行。显式启用后仅安全只读、暂时不可用或降级且下一候选 AVAILABLE 才可选择。人工验证、缺失认证、未验证和高副作用操作均不可通过 fallback 绕过。当前真实 Mobile 不可配置成功，不会作为生产兜底。

## Mobile 占位

新增 MobileAdapter 抽象、UnconfiguredMobileAdapter、FakeMobileAdapter。真实实现能力均为 false、health_check=false，读取报 EXECUTOR_NOT_CONFIGURED；Fake 只返回固定 fixture 数据。mobile.app.launch 未实现，未安装 Appium/uiautomator2，不启动任何设备或 App。

## Capability API

新增管理鉴权接口：`GET /api/accounts/{id}/capabilities`，mode=PRODUCTION / DIAGNOSTIC。

返回 Operation、selected_executor、risk_level、status、mode、reason、error_code、candidates。候选包含 executor/status/runtime_status/verification_level/reason。不存在或已删除账号 404；无效 mode 422；鉴权失败 401。

API→CapabilityService→UnitOfWork→Repository。未输出 Cookie、Token、Storage State、账号号码、节点 URL、Worker ID 或 Redis Key。backend 对 browser_data 增加只读挂载，查询使用已有加密 State，不修改文件。

## Capability Matrix

见 [qq-capability-matrix.md](qq-capability-matrix.md)。包含全部 16 个 Operation 的 OneBot/Browser/Mobile 验证状态及 Production 结论，保留操作不标为 Supported。

## 当前 Production 能力

**新 Router 当前允许生产选择的 QQ Operation：0 项。**

浏览器技术能力经过真实验证，但 QQ 业务没有 REAL_ENV_VERIFIED 的证据。框架完成不代表业务真实可执行。

旧 Task 保持运行兼容，Router 尚不是旧执行 API 的全局门禁。本阶段不改变旧接口权限或批量重构旧插件。新业务必须优先使用 Operation+Router，并在无候选时停止；后续仍需要真实环境验证和逐步迁移。

## 测试结果

- 普通 pytest：**495 passed / 49 skipped**。
- Chromium integration：**43 passed**，既有 OneBot/Web/Browser 回归未退化。
- 不同测试通过数：**538**；收集总数 **544**，其余 6 项需真实 OneBot 条件，尚未执行。
- 本阶段新增 **89 项** Router/Resolver/API/Service/Mobile 测试。
- Ruff：All checks passed。
- Alembic check：No new upgrade operations detected。
- Compose config --quiet：退出码 0。
- 保留两条已有 Starlette/httpx/AnyIO 弃用提示，无新增失败。

覆盖 Operation 元数据与白名单、优先级、显式执行器、不支持候选跳过、四个验证等级、不配置/过期/降级/缺失状态、账号隔离、人工验证、fallback 及风险门槛、API 成功/404/401/422/脱敏。正向 AVAILABLE 测试仅通过内部测试构造模拟未来真实证据，没有修改产品登记表。

## Docker 验证

完成新镜像构建及服务更新，backend、worker、scheduler、onebot-listener、mysql、redis 六个常驻服务均 healthy。

实际 HTTP + MySQL + Redis 验收：两个 mode 均 HTTP 200，分别返回 16 个 Operation，全部 selected_executor=null；没有创建 Execution；未知账号返回 404。临时账号通过 API 创建并删除，删除后查询返回 404。

结果见 [phase-8c-capability-api-verification.json](phase-8c-capability-api-verification.json)。此验证只检查能力查询，不执行任何业务。

## 修改文件

新增：

- `backend/app/executors/`：`__init__.py`、`models.py`、`catalog.py`、`resolver.py`、`router.py`、`policy.py`、`errors.py`。
- `backend/app/adapters/mobile.py`。
- `backend/app/services/capabilities.py`。
- `backend/app/api/capabilities.py`。
- `backend/tests/test_executor_router.py`、`test_capability_api.py`。
- `docs/executor-router.md`、`qq-capability-matrix.md`、本报告和 API 验证 JSON。

修改：

- `backend/app/main.py`：注册服务和 API。
- `backend/app/services/runtime_adapters.py`：注入账号绑定 Router。
- `backend/app/core/config.py`、`.env.example`、`docker-compose.yml`：按 Operation 优先级配置与 backend 只读 State 卷。
- `README.md`：能力查询、验证门槛和使用边界。

## 数据库变化

无表/字段/索引变更，无新增 Alembic Migration，无新增业务任务定义。Operation 和验证等级是受信任代码登记。API 验收只创建后软删除临时账号，无 Execution。

## 已知问题

能力查询是本地状态快照，不是执行预约、锁或永久授权；真正执行时应重新验证运行状态。没有做新的真实 QQ 登录探测，State 存在不能证明会话有效。旧任务入口尚未统一经过 Router。

## 尚未完成

真实 NapCat、真实 QQ Web 登录、真实任务/活动中心读取尚未验证。没有移动端真实实现、Operation execute 或写操作，也没有开启任何绕过验证的机制。下一阶段应为 Phase 8D 真实环境验证，获得证据后再更新矩阵。
