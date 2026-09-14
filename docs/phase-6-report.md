# Phase 6：完整 NapCat / OneBot Adapter 验收报告

验收日期：2026-09-11。基线为 Phase 1–5 的 108 项测试。当前实现不依赖真实 QQ 登录。

## 完成内容

完成多节点标准 OneBot 11 Adapter、独立 WebSocket Listener、事件总线、登录状态同步、能力检查、Fake Adapter、数据库迁移与管理接口。
保留 API → Service → Repository 层次。没有开发真实 QQ 任务、前端、浏览器或手机自动化。

## Adapter 架构

```text
Account.node_id → Node → HTTP/WS Endpoint + secret_ref
                           ↓
TaskEngine → AdapterRegistry → OneBotAdapter → OneBotHttpClient → NapCat
                                     ↑
                         OneBotService 按账号节点注入

独立 onebot-listener
  → 每节点 OneBotWebSocketClient
  → 类型化 Event Parser
  → asyncio.Queue EventBus
  → LoginStatusHandler → Service → Repository → Account / Node
```

`OneBotService` 按节点配置版本复用 AsyncClient，通过引用计数避免关闭仍在使用的连接，退出时统一释放。
Worker 和本地 `task_engine()` 使用相同的按节点注入方式。Node 更新后配置版本递增，旧 Listener 的观察不能覆盖新状态。
API 没有持有或访问 SQLAlchemy Session，也不直接调用第三方 HTTP。

## HTTP 能力

| 方法 | 分类 | 输出 |
| --- | --- | --- |
| health_check / get_status | READ | OnlineStatus |
| get_login_info | READ | LoginInfo |
| get_version_info | READ | VersionInfo |
| get_friend_list | READ | list[FriendInfo] |
| get_group_list / get_group_info | READ | list[GroupInfo] / GroupInfo |
| get_stranger_info | READ | StrangerInfo |
| send_private_msg / send_group_msg | WRITE | MessageReceipt |
| delete_msg | WRITE | None |

`ActionMetadata` 标明操作分类、幂等性和可重试性。ADMIN 类型预留，未添加管理类私有接口。
`EmptyParams`、`UserParams`、`GroupParams`、`PrivateMessageParams`、`GroupMessageParams`、`DeleteMessageParams` 和 MessageSegment 校验输入。
统一 HTTP RPC 解析 status / retcode / data / message / wording 为 AdapterResponse；第三方自由文本不会出现在公共错误中。
成功响应的 message/wording 被清空。返回列表、布尔值、账号 ID 等使用严格类型校验。
`get_login_info` 保留先执行在线检查的兼容行为，合计两次只读 RPC。

## WebSocket 能力

正向 WS 使用 Authorization header 鉴权，支持接收、断线、重连与优雅退出。
退避默认为 1、2、4、8、16、30 秒，上限可配置；必须收到跨越稳定窗口的合法心跳，才会重置退避。
不因不断快速握手成功而重置。即使持续收到普通消息，超过心跳期限仍会重新连接。

MetaEvent、MessageEvent、NoticeEvent、RequestEvent 与 UnknownEvent 统一建模。
原始 raw_event 仅保留内存，不包含于 repr 或 model_dump；畸形事件返回 UnknownEvent 并记录固定事件名。
EventBus 使用容量 1000 的 asyncio.Queue 提供背压。订阅者并发执行，有单独超时和异常隔离。
退出先取消子任务再等待清理，已回归验证无遗留 EventBus 消费者。

## Capability

AdapterRegistry 提供 get / require。TaskContext 使用 `context.get_adapter("onebot")`。
任务声明：

```python
required_capabilities = {"onebot": {"login_info", "friend_list"}}
```

能力按 Adapter 分组，方便未来组合 Browser / Mobile。Engine 在 execute 前检查，缺失时返回 ADAPTER_NOT_CONFIGURED 或 CAPABILITY_UNSUPPORTED。
OneBot 提供登录、状态、版本、好友、群、私信、群消息、撤回等标准能力；qzone、mobile、mobile_automation 为 false。
能力表示本地实现支持范围，不能代替远端版本兼容性验证。
FakeOneBotAdapter 支持成功、连接失败、超时、业务错误和无效响应，插件测试不创建真实网络连接。

## Node 与账号映射 / 数据库变化

新增 Alembic 版本 `d6a01_onebot_nodes`，前置版本 `c888eb342135`。
仅扩展 `node` 表；Account.node_id 和执行历史结构保留。

| 字段 | SQL 类型 | 含义 |
| --- | --- | --- |
| onebot_http_url | VARCHAR(2048), nullable | 节点 HTTP 地址 |
| onebot_ws_url | VARCHAR(2048), nullable | 节点正向事件 WS 地址 |
| secret_ref | VARCHAR(128), nullable | 环境变量映射中的凭据引用 |
| config_revision | INTEGER, NOT NULL, default 1 | 配置版本，阻止旧事件写回 |
| ws_state | VARCHAR(32), NOT NULL, default UNKNOWN | 最近 WS 状态 |
| ws_seen_at | DATETIME, nullable | Listener 最近观察时间，UTC |
| checked_at | DATETIME, nullable | HTTP 健康检查时间，UTC |

`node.status` 保存聚合连接状态。HTTP+WS 正常为 CONNECTED，HTTP 正常而 WS 不可用为 DEGRADED，HTTP 失败为 DISCONNECTED，认证失败为 AUTH_FAILED。
观察超过三个轮询周期视作陈旧，汇总按 UNKNOWN 处理。HTTP 可达但离线显示 DEGRADED。
Account.online_status 是最近观察值；HTTP 不可达时设 UNKNOWN，明确离线设 OFFLINE。
只有节点返回的 QQ 身份与绑定账号一致，才标记 ONLINE。身份错配阻止任务执行。
单次异常不会修改账号 ACTIVE/DISABLED。重绑节点或替换连接配置会重置账号在线状态。
迁移在 MySQL 应用成功；pytest 验证 SQLite 升级、降级、再次升级与模型一致性。

## 异常与重试

统一 OneBotError，包含 error_code / message / action / retryable。
子类覆盖 Connection、Timeout、Authentication、Api、InvalidResponse、NotConnected、UnsupportedAction、RateLimit；另外提供 ArgumentError 拦截无效输入。
保留通用 AdapterConnectionError / AdapterTimeoutError / AdapterResponseError 的继承兼容性。

仅 READ 的连接异常、网络超时、临时 5xx 可以短重试：默认一次、最多两次，间隔 0.1 / 0.2 秒。
认证、限流、业务失败、参数或返回格式错误不重试。发送和撤回均不自动重试，也不宣称 exactly-once。
Adapter 预算耗尽后 retryable=false，Worker 的自动重试白名单不包括 ONEBOT_*；不会把两层预算相乘。
需要手动补执行时仍使用既有新 execution + parent_execution_id 审计链。

## 安全处理

凭据仅位于 `.env` / 进程环境，数据库只存 secret_ref。ONEBOT_NODE_TOKENS 为 SecretStr JSON 映射。
默认无全局单账号注入；只有显式 default 引用可以使用全局 ONEBOT_* 配置。
URL 拒绝凭据、查询串和 fragment；HTTP 不跟随重定向，不读取系统代理；WS 同样禁用环境代理。
SensitiveDataFilter 遮蔽 Bearer、token、Cookie、Authorization、password、session key 等；
结构化日志采用固定事件及字段白名单，不输出异常原文，禁用 HTTPX/httpcore/websockets 第三方内容日志。

没有公开发送/撤回 API。测试中的发送全部交给 Fake 或 MockTransport，从未向真实 QQ 发送消息。
secret storage 当前为环境变量映射，尚不是 Vault/KMS；变更 token 必须重启使用该环境的进程。

## API 变化

- `POST /api/nodes`、`GET /api/nodes` 增加节点地址及 secret_ref。
- `PUT /api/nodes/{id}/connection`：需要管理认证，完整替换连接配置，204；版本递增并重置观察状态。
- `GET /api/nodes/{id}/health`：需要管理认证，只执行读 RPC 并同步本地健康快照。
  返回 node_id、adapter_type、connection_state、account_id、account_ids、login_info、version、error_code、checked_at、metrics，不含地址或凭据。
- `GET /api/system/health` 增加可选 OneBot 状态汇总；是否返回 200/503 仍只由数据库和 Redis 决定。

## Observability

提供进程内计数器：onebot_http_requests_total、onebot_http_errors_total、onebot_ws_connected、onebot_ws_reconnect_total、onebot_events_total。
HTTP 计数通过节点 health 输出，包括失败探测；WS 和事件计数由独立 Listener 的结构化日志输出。
这些计数随进程或节点客户端重建而重置，不是跨进程聚合统计。本阶段未引入 Prometheus。

## 修改文件

以下均相对于项目根目录：

| 范围 | 文件 |
| --- | --- |
| HTTP Adapter | backend/app/adapters/onebot/adapter.py、http_client.py、client.py、schemas.py、exceptions.py、capability.py |
| WS 与测试替身 | backend/app/adapters/onebot/websocket_client.py、events.py、listener.py、fake.py |
| Adapter Registry | backend/app/adapters/registry.py |
| 节点数据与管理 | backend/app/models/node.py、repositories/management.py、schemas/management.py、schemas/onebot.py、services/onebot.py、services/management.py、api/onebot.py |
| 任务注入 | backend/app/tasks/base.py、engine.py、bootstrap.py、services/task_runtime.py、services/dispatch.py、workers/worker.py |
| 应用与健康 | backend/app/main.py、core/config.py、core/logging.py、services/system_service.py、schemas/system.py |
| Migration | backend/alembic/versions/d6a01_onebot_nodes.py |
| 新测试 | backend/tests/test_onebot_http_full.py、test_onebot_ws.py、test_onebot_nodes.py、test_onebot_integration.py |
| 既有资源清理测试适配 | backend/tests/test_task_engine.py、test_foundation.py |
| 依赖、配置、文档 | backend/pyproject.toml、backend/requirements.lock、docker-compose.yml、.env.example、README.md、docs/phase-6-report.md |

## 测试结果

开始前：108 passed，Ruff 通过，旧版本 Alembic 模型一致，原容器 healthy。
完成后：**202 passed**，包含原有 108 项与新增 94 项，完整 task/database/migration/Redis/Worker 测试全部通过。

```sh
backend/.venv/bin/python -m pytest backend/tests -q -W error::pytest.PytestUnraisableExceptionWarning
backend/.venv/bin/ruff check backend/app backend/tests backend/alembic scripts
docker compose config --quiet
backend/.venv/bin/alembic -c backend/alembic.ini check
```

最终 pytest：202 passed, 2 warnings；Ruff：All checks passed；Alembic：No new upgrade operations detected。
两项 warning 来自 Starlette 测试客户端的依赖弃用提示，不是业务失败或未清理协程。
已将 unraisable 异常按错误处理并通过。

覆盖所有标准方法、输入/输出校验、错误分类、短重试、不重试写操作、敏感信息过滤、WS 认证、
事件解析、心跳期限、重连退避上限和稳定后重置、订阅者故障隔离、多个节点和凭据隔离、
身份错配、配置版本隔离、任务能力检查、节点 API 认证以及核心健康隔离。
真实本地 HTTP server + WebSocket server 同时运行，首次主动断线后自动恢复，并通过 Listener 同步账号。

## Docker 验证

已构建并应用迁移；新增 onebot-listener 独立进程。
验收期间停止 onebot-listener 后：Listener 正常 Exited(0)，API live 与 health 均 HTTP 200，
worker-status 管理接口 HTTP 200，backend / worker / scheduler / mysql / redis 保持 healthy。
随后恢复 Listener。运行环境没有 NapCat，核心健康仍为 api=UP、status=ok。
最终常驻服务：backend、worker、scheduler、onebot-listener、mysql、redis 均 healthy；migrate 为 Exited(0)。

## NapCat 真实联调

**真实 NapCat 未验证。** 本地全局 HTTP/WS 均未配置，数据库中没有已配置的 OneBot 节点。
未取得真实 NapCat 版本，不宣称任何具体版本已兼容。使用 Mock Server 完成自动化准出。
未来真实联调仅执行 health_check、get_login_info、get_status、get_version_info、get_friend_list、get_group_list。
依据：[OneBot 11 标准 API](https://github.com/botuniverse/onebot-11/blob/master/api/public.md)、
[正向 WS 协议](https://github.com/botuniverse/onebot-11/blob/master/communication/ws.md)、
[NapCat 官方接入文档](https://napneko.github.io/use/integration)。

## 已知问题与尚未完成

- Listener 当前按单实例部署，没有多 Listener 节点分片/所有权租约；多 Worker 与多 Node 已支持。
- EventBus 为有界内存队列，不保证跨重启持久化或事件重放；raw_event 不作为审计日志保存。
- Account.online_status 为最近观察值；Listener 整体停止时应结合 Node.checked_at 与健康状态判断新鲜度。
- Node 配置的 WS 地址必须提供事件和 heartbeat；只提供 API RPC 的 WS 路径会触发心跳超时重连。
- Docker Listener 健康检查目前检查进程存活，不代表 NapCat 在线；节点就绪状态由 Node health 提供。
- 计数器暂不聚合到 Prometheus。未来可替换 secret storage，补充指标导出与事件持久化。
- 真实 NapCat 版本兼容性待只读联调。发送消息等写能力只有 Mock 验证。
- Phase 7 Playwright、Phase 8 真实业务插件、Phase 9 Vue、Phase 10 压测和完整部署验收不在本阶段实现。
