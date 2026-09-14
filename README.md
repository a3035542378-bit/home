# 账号自动化任务管理平台

已交付 Phase 1–7、Phase 8A 和 Phase 8B-1（Phase 6.5 真实 NapCat 联调仍待实例）：基础工程、数据模型与管理 API、Task Engine、Redis Stream、Worker、Lease、Retry、APScheduler，以及多节点 OneBot Adapter、独立 WS Listener 和 Playwright Browser Adapter。
Python 3.12、FastAPI、SQLAlchemy 2.x、Pydantic、MySQL 8、Redis、Alembic。

账号只用于本人管理。验证挑战返回 NEED_USER_ACTION，等待本人处理；未实现任务返回 SKIPPED，不伪造成功。
当前没有 Vue 管理后台，使用 `/docs` 管理 API。已有 Mock 与只读 Probe 插件，Browser Probe 已通过真实 Chromium 任务链路；没有接入真实 QQ 业务任务。

## 启动

macOS 先启动 Docker Desktop：

```sh
docker desktop start
```

新部署在项目根目录生成配置（仅使用 Python 标准库，已有 `.env` 不会覆盖）：

```sh
python3 scripts/init_env.py
docker compose up -d --build
docker compose ps
curl --fail http://localhost:8000/api/system/health
```

也可复制 `.env.example` 并自行填写空字段。不要直接使用空配置启动。
`migrate` 服务成功退出（Exited 0）是正常状态；后端等待它完成 Alembic 迁移后启动。
后端、Worker、Scheduler、OneBot Listener、MySQL、Redis 应为 healthy。数据保存在命名卷，`docker compose down` 保留数据；
`docker compose down -v` 会删除数据，不要用于日常重启。

接口文档：<http://localhost:8000/docs>。公开探针：

- `GET /api/system/live`：进程存活，HTTP 200。
- `GET /api/system/health`：MySQL/Redis 探测，正常 200，依赖异常 503。

管理接口需要 `Authorization: Bearer <ADMIN_ACCESS_TOKEN>`。在本机 `.env` 查看该值，
在 Swagger 的 Authorize 中填入；不要把凭据粘贴到日志、文档或 Git。
未配置管理凭据返回 503，错误凭据返回 401。端口只绑定 localhost。

## API

| 方法与路径 | 用途 |
| --- | --- |
| GET /api/accounts | 分页账号列表 |
| POST /api/accounts | 创建账号 |
| GET /api/accounts/{account_id} | 查询账号 |
| PUT /api/accounts/{account_id} | 更新昵称、状态或节点 |
| DELETE /api/accounts/{account_id} | 软删除并关闭配置；运行中拒绝删除 |
| GET /api/accounts/{account_id}/tasks | 查询已配置任务 |
| PUT /api/accounts/{account_id}/tasks/{task_code} | 创建或更新单个配置 |
| PATCH /api/accounts/{account_id}/tasks | 批量开关该账号已有配置 |
| GET /api/tasks、POST /api/tasks | 查询/创建任务定义 |
| GET /api/nodes、POST /api/nodes | 查询/创建节点及 OneBot 地址、凭据引用 |
| PUT /api/nodes/{id}/connection | 完整替换节点连接配置并重置健康状态 |
| GET /api/nodes/{id}/health | 只读探测 OneBot 并同步账号状态，不返回地址或凭据 |
| GET /api/executions | 分页执行记录，可按 account_id/status 过滤 |
| GET /api/executions/{execution_id} | 执行详情 |
| POST /api/tasks/{task_code}/execute | 创建 PENDING 执行并持久化投递请求，返回 202 |
| POST /api/executions/retry-failed | 指定账号/日期补执行，创建新的 RETRY 记录 |
| GET /api/system/worker-status | Worker 心跳、在线状态、当前执行列表 |

分页参数 `offset >= 0`、`1 <= limit <= 100`。业务错误返回 `error_code` 和中文 `message`。
账号唯一键为 `(platform, account_no)`，软删除后继续保留该键和历史执行记录。
任务配置唯一键为 `(account_id, task_code)`。账户身份不能通过更新接口替换。
`default_enabled` 目前作为定义元数据保存，创建账号不会自动开启任何任务，须显式配置。

创建任务定义只写入元数据，不创建 Python 插件。Engine 会同时验证 Registry、定义、账号和开关。
HTTP 手动执行只写 Execution/Outbox。独立进程补投 Redis，Worker 调用 Engine 并保存终态；202 表示已持久接受，不代表任务已完成。

## 本地开发与测试

```sh
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.lock -e 'backend[test]'
python3 scripts/init_env.py
docker compose up -d mysql redis
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --reload --no-access-log
```

上述命令从根目录运行，Settings 读取根目录 `.env`。单元测试使用独立 SQLite 文件并开启外键，
OneBot 测试使用 httpx.MockTransport、Fake Adapter 和本地 HTTP/WS Mock Server；不要求 QQ 登录，不访问真实 NapCat。
新增分布式测试需要真实 Redis，默认 `redis://127.0.0.1:6379/15`，可用 `TEST_REDIS_URL` 覆盖。
测试使用唯一前缀并仅删除自己创建的 key，不运行 FLUSHDB。

```sh
backend/.venv/bin/python -m pytest backend/tests -q
backend/.venv/bin/python -m pytest backend/tests/test_database.py backend/tests/test_migration.py -q
backend/.venv/bin/python -m pytest backend/tests/test_task_engine.py -q
backend/.venv/bin/ruff check backend/app backend/tests backend/alembic scripts
```

运行依赖锁在 `backend/requirements.lock`，变更依赖后用 `uv pip compile backend/pyproject.toml -o backend/requirements.lock` 更新。

## 数据库与迁移

业务表：`account`、`node`、`task_definition`、`task_config`、`task_execution`、`task_outbox`；另有 `alembic_version`。
首个迁移是 `733e680fde79`，本轮迁移 `c888eb342135` 增加队列、重试和租约字段。详见 [Phase 4–5 报告](docs/phase-4-5-report.md)。
应用启动不调用 `create_all`。

```sh
backend/.venv/bin/alembic -c backend/alembic.ini current
backend/.venv/bin/alembic -c backend/alembic.ini check
backend/.venv/bin/alembic -c backend/alembic.ini revision --autogenerate -m '迁移说明'
backend/.venv/bin/alembic -c backend/alembic.ini upgrade head
```

生成迁移后必须检查内容，再运行测试及升级。`downgrade base` 会删除全部业务表，
仅允许在可丢弃的测试数据库验证；单元测试会在临时 SQLite 中完成升级/回退/再升级。

## Task 插件扩展

在 `backend/app/tasks/builtin/` 新建独立 Python 文件，继承并注册即可。启动工厂自动发现该目录，
无需修改 Engine 或维护 if/else 分支。插件目录仅包含受信任项目代码，不能从 HTTP 上传执行 Python。

```python
from app.models.common import ExecutionStatus
from app.tasks.base import BaseTask, TaskContext, TaskResult
from app.tasks.registry import register_task

@register_task
class DailyCheckinTask(BaseTask):
    task_code = "DAILY_CHECKIN"
    task_name = "每日签到"

    async def execute(self, context: TaskContext) -> TaskResult:
        return TaskResult(
            success=False,
            status=ExecutionStatus.SKIPPED,
            message="尚未实现签到能力",
            error_code="NOT_IMPLEMENTED",
        )
```

通过管理 API 创建对应 TaskDefinition、Account、启用 TaskConfig 后，在 Swagger 的 execute 接口提交
`{"account_id": 1}`，查询返回的 execution_id。新增插件后重建镜像并更新 API、Worker、Scheduler。
旧版 `TaskEngine.execute()` 保留供兼容测试，生产入口统一通过队列；Worker 使用 `TaskEngine.run()`
执行已经领取的上下文，避免创建第二条 execution 或绕开租约。

TaskContext 包含不带凭据的 AccountContext、配置、execution_id、注入的 adapters。
TaskStore 是持久化 Protocol，测试可替换 mock，生产由 Service → Repository 保存。
TaskResult 强制终态、success/status 一致、带时区时间，拒绝 data 中的敏感字段名。
插件只能返回可公开的 message/data，不能在自由文本中夹带凭据或完整第三方响应。
异常只保存统一错误信息，不保存异常原文。

## Redis Queue、Worker 与状态流转

链路：API → 数据库 Execution + Outbox → Redis Stream → Worker → TaskEngine → 数据库终态 → ACK。
数据库事务一次性保存 PENDING 执行和 Outbox，避免 DB 成功而 Redis 失败导致永久丢单。
Worker/Scheduler 每隔 `MAINTENANCE_INTERVAL` 补投；长期 PENDING 消息每隔 `OUTBOX_REPUBLISH_SECONDS`
允许重复投递，以恢复 Redis 重启后的短暂数据丢失。数据库状态及执行占用防止重复运行。

Redis 结构：

- `qq:task:stream`：消费组 `qq-workers`，XREADGROUP、XACK、Pending、XAUTOCLAIM。
- `qq:task:dlq`：畸形消息、无法恢复或自动重试耗尽的消息；畸形原文只保存摘要。
- `qq:task:dlq:index`：DLQ 幂等索引，避免相同执行/错误重复归档。
- `task-lock:{account_id}:{task_code}`：带随机所有者值与 TTL 的分布式锁。
- `worker:{worker_id}`：带 TTL 的 Worker 状态。

本 Stream 只支持一个逻辑消费组，多 Worker 同属该组。ACK 后删除消息；未 ACK 不裁剪，避免误删 Pending。
这是至少一次消息投递；外部非幂等副作用不保证 exactly-once。

允许 PENDING → RUNNING → SUCCESS / FAILED / SKIPPED / NEED_USER_ACTION。
消费前配置关闭则 PENDING → SKIPPED。终态不可改回 RUNNING，重试新建记录。
同账号/任务在 PENDING 时就占用数据库执行位，多 Worker 再通过 Redis 锁和数据库 CAS 双重保护。

本地启动（根目录，先安装依赖和迁移）：

```sh
backend/.venv/bin/python -m app.workers.worker
backend/.venv/bin/python -m app.scheduler.scheduler
```

扩展 Worker：

```sh
docker compose up -d --scale worker=2
docker compose logs -f worker scheduler
```

默认每个 Worker 并发 5 个任务。收到 SIGTERM/SIGINT 后停止接收，在退出宽限期内等待完成；
超时则取消本地协程、停止续租，保留 RUNNING/Pending 给 Recovery。插件必须遵守 asyncio 取消协议，
不能阻塞事件循环或吞掉 CancelledError。Worker 容器健康探针检测进程；业务活性通过 worker-status 查询。

## Lease、Retry 与 Recovery

执行开始保存 worker_id、lease_token、lease_until、heartbeat_at；运行期间每隔锁/租约较短 TTL 的三分之一续租。
Redis 续租和释放均用 Lua 比较所有者；过期 Worker 不能释放新锁。终态写入还需匹配数据库租约所有者和有效期。

Worker 或 Scheduler 定期将过期 RUNNING 标记 FAILED / WORKER_LEASE_EXPIRED 并释放数据库占用。
旧版无租约的 RUNNING 记录超过兼容超时也可恢复。恢复不自动重放，因为外部结果可能未知。

`POST /api/executions/retry-failed` 请求体可以为空，或：

```json
{"account_id": 1, "date": "2026-09-11"}
```

默认日期由 BUSINESS_TIMEZONE 决定。只补该日期最新的 FAILED 叶节点，排除账号失效、任务关闭、
已有 PENDING/RUNNING、当日成功或最新结果需要人工处理的任务。旧记录没有 business_date 时使用创建时间和配置时区。
原记录保留 FAILED，新记录 parent_execution_id 指向父记录，retry_count 递增，trigger_type=RETRY。
父节点唯一约束防止两个请求创建同一个父节点的多个重试分支。

系统自动重试仅允许 ADAPTER_TIMEOUT、ADAPTER_CONNECTION_ERROR，且插件必须声明 `retry_safe=True`。
默认最多 2 次，延迟 5 秒、15 秒；通过 Outbox.available_at 实现，不占用 Worker 睡眠。
业务明确失败、任务整体超时、人工验证、租约过期不会自动重试。次数耗尽进入 DLQ。
手工补执行不受自动次数上限阻止，但重试链计数不会重置，防止重新开启无限自动重试。

Redis 不可用时 API 仍可返回 202（已持久化到 Outbox）；没有 Worker 在线时任务保持 PENDING。
worker-status 在 Redis 不可用时返回 503。心跳 TTL 过期的 Worker 从在线列表消失，正常退出短期显示 OFFLINE。
核心 health 与 NapCat 无关；api、database、redis 正常即可用。

## Scheduler

独立 APScheduler 进程只创建执行和投递消息，不执行插件。默认 Asia/Shanghai 每天 01:00，
由 BUSINESS_TIMEZONE、SCHEDULE_HOUR、SCHEDULE_MINUTE 配置。
数据库 schedule_key 唯一约束按账号、任务、业务日期、daily 槽位去重，多个 Scheduler 不会重复生成同日记录。
SCHEDULER_ENABLED=false 关闭每日投递，但保留恢复和 Outbox 维护。
当前不提供离线期间漏调度的自动补建，也没有复杂 Cron UI。

## 全链路验收

提供四个明确标记的安全插件：MOCK_SUCCESS、MOCK_FAIL、MOCK_TIMEOUT、MOCK_NEED_USER_ACTION。
通过 `/api/tasks` 创建对应定义，通过 `/api/accounts/{id}/tasks/{code}` 开启配置。
MOCK_SUCCESS 仅表示模拟逻辑成功，不代表任何 QQ 操作。

```sh
backend/.venv/bin/python -m pytest backend/tests -q
backend/.venv/bin/python scripts/e2e_queue.py
```

第二条命令是破坏性故障模拟：仅在验收环境执行，会 SIGKILL 本项目持有测试任务的 Worker，
等待真实租约过期，再恢复 Worker；不会连接 QQ。成功后软删除临时账号，保留执行审计。

## OneBot / NapCat（Phase 6）

先在自己管理的环境安装并登录 NapCat，启用 OneBot 11 HTTP 服务和**正向 WebSocket** 事件服务。
NapCat 是外部依赖，不打包进此项目；未配置或未登录时 API、Worker、Scheduler 仍可运行。
配置端口、防火墙和访问凭据可参考 [NapCat 官方接入说明](https://napneko.github.io/use/integration)。
项目使用 [OneBot 11 标准 API](https://github.com/botuniverse/onebot-11/blob/master/api/public.md)，未实现 NapCat 私有业务接口。

每个账号绑定 `node_id`，每个 Node 独立配置 HTTP/WS 地址与 `secret_ref`。一个 NapCat 实例对应一个登录 QQ；
允许一个节点关联多条账号记录，但只会把返回的 QQ 号对应的记录标记 ONLINE。身份不匹配时任务会在执行前失败。
任务声明 `required_capabilities = {"onebot": {"login_info", "friend_list"}}`，通过
`context.get_adapter("onebot")` 取得 Adapter。Worker 和本地 `task_engine()` 都按 Node 注入，不能在插件中自行创建客户端。

通过带管理认证的 Swagger `POST /api/nodes` 创建节点，例如：

```json
{
  "name": "本人 QQ 节点 A",
  "adapter_type": "ONEBOT",
  "onebot_http_url": "http://host.docker.internal:3000",
  "onebot_ws_url": "ws://host.docker.internal:3001/event",
  "secret_ref": "node_a"
}
```

上面的地址仅说明结构，须替换成实际配置。容器访问 macOS 宿主用 `host.docker.internal`，
宿主 Python 访问本机用 `127.0.0.1`。WS 选择提供事件的 `/event` 或 `/`，不要使用仅 RPC 的 `/api`。
URL 禁止用户名、密码、查询参数及 fragment。token 只经 Authorization header 发送。

`.env` 的 `ONEBOT_NODE_TOKENS` 保存 JSON 字符串映射，键为 `secret_ref`（如 `node_a`），值为自行设置的 NapCat token。
默认空映射 `'{}'`，不在文档中放凭据示例。缺少引用会返回 `NODE_SECRET_NOT_CONFIGURED`，不回退到其他节点。
没有设置 `secret_ref` 表示此节点不发送认证 header。
仅显式设置 `secret_ref="default"` 的节点可使用 `ONEBOT_ACCESS_TOKEN`，并在节点地址为空时使用全局
`ONEBOT_HTTP_URL`、`ONEBOT_WS_URL`。全局配置不会自动分配给所有账号。
修改环境变量后重建相应进程；管理 API 修改节点地址后 Listener 自动重连，旧版本事件不能回写新配置状态。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| ONEBOT_HTTP_TIMEOUT | 5 秒 | 单个 HTTP 读写阶段超时 |
| ONEBOT_CONNECT_TIMEOUT | 3 秒 | HTTP / WS 建连超时 |
| ONEBOT_MAX_RETRIES | 1 | 只读操作短重试，最大 2 |
| ONEBOT_WS_RECONNECT_MIN_SECONDS / MAX_SECONDS | 1 / 30 秒 | WS 退避范围 |
| ONEBOT_WS_HEARTBEAT_TIMEOUT | 60 秒 | 未收到合法 heartbeat 则断开重连 |
| ONEBOT_POLL_INTERVAL | 15 秒 | 节点配置刷新、HTTP 回退探测周期 |
| ONEBOT_NODE_TOKENS | 空映射 | 每个 Node 凭据引用对应的环境变量映射 |

本地兼容 `ONEBOT_TIMEOUT_SECONDS`、`ONEBOT_RETRIES`；新设置优先，旧重试值最多折算为 2。
Compose 显式使用新设置。`get_login_info()` 保留先检查在线状态的行为，可能包含两次只读 RPC。

HTTP 能力：`health_check()`、`get_login_info()`、`get_status()`、`get_version_info()`、`get_friend_list()`、
`get_group_list()`、`get_group_info(group_id)`、`get_stranger_info(user_id)`、`send_private_msg()`、
`send_group_msg()`、`delete_msg()`。输入和输出均校验；列表返回类型化模型列表。
发送与撤回仅为内部能力，没有公开发送 API，不自动重放写请求。

`capabilities()` 返回标准能力支持情况，`qzone`、`mobile_automation` 为 false；这是本地实现声明，
不保证每个 NapCat 版本均实现全部标准端点。上游不支持时返回 `ONEBOT_UNSUPPORTED_ACTION`。
READ 的连接错误、超时、5xx 可在 Adapter 内短重试；认证错误、限流、业务失败、格式错误立即返回。
用尽预算后异常 `retryable=false`。Worker 的自动重试白名单不含 `ONEBOT_*`，避免重试相乘；
用户确认后手动补执行仍创建新的 execution 记录。

独立运行方式：

```sh
docker compose up -d --build
# 或本地开发，在项目根目录读取 .env：
backend/.venv/bin/python -m app.adapters.onebot.listener
curl --fail http://localhost:8000/api/system/health
```

节点健康在 Swagger 的 `GET /api/nodes/{id}/health` 查看（先 Authorize）。也可在 shell 已安全设置
`ADMIN_ACCESS_TOKEN` 后调用，不要开启 shell trace 或共享含凭据的命令输出：

```sh
curl --fail -H "Authorization: Bearer ${ADMIN_ACCESS_TOKEN}" http://localhost:8000/api/nodes/1/health
```

HTTP+WS 正常为 CONNECTED；HTTP 正常而 WS 中断为 DEGRADED；HTTP 失败为 DISCONNECTED；认证失败为 AUTH_FAILED。
Listener 状态超过 3 个轮询周期未刷新，查询时按 UNKNOWN 处理，不继续声称 WS 正常。
`Account.online_status` 是最近观察值，排查在线状态时同时看 Node health 的 `checked_at`；账号的 ACTIVE/DISABLED 不受单次故障改变。
核心 `/api/system/health` 的 HTTP 状态码只取决于 MySQL/Redis，OneBot 汇总是附加信息。

WS 事件先解析为 Meta/Message/Notice/Request/Unknown 模型，再进入有界内存队列；Handler 异常相互隔离。
LoginStatusHandler 按节点和 self_id 同步账号，HTTP 周期探测作为回退。
事件原文只保留在内存的 `raw_event`，不写数据库、日志或 API；重启不会重放历史事件。
Listener 当前应保持单实例，后续若要横向扩容需增加节点分片或所有权租约。

```sh
backend/.venv/bin/python -m pytest backend/tests -q
backend/.venv/bin/python -m pytest backend/tests/test_onebot*.py -q
```

当前真实 NapCat 未验证。Mock 测试覆盖 HTTP 与 WS 同时运行、连接恢复、认证失败、未知事件、
多节点隔离和任务能力检查。真实联调只允许读接口；本阶段没有向 QQ 发送消息。
详见 [Phase 6 验收报告](docs/phase-6-report.md)。

## 配置与安全

| 变量 | 用途 |
| --- | --- |
| DATABASE_URL | 本地进程数据库 URL，必填，无密码默认值 |
| DOCKER_DATABASE_URL | Compose 内数据库 URL，host 应为 mysql |
| MYSQL_DATABASE、MYSQL_USER、MYSQL_PASSWORD、MYSQL_ROOT_PASSWORD | MySQL 初始化配置 |
| ADMIN_ACCESS_TOKEN | 管理接口 Bearer 凭据 |
| REDIS_URL | 本地 Redis URL；Compose 使用服务名 redis |
| DEPENDENCY_TIMEOUT_SECONDS | 健康探针超时 |
| ONEBOT_HTTP_URL、ONEBOT_WS_URL、ONEBOT_ACCESS_TOKEN | NapCat 接入设置 |
| ONEBOT_TIMEOUT_SECONDS、ONEBOT_RETRIES | 调用超时与重试上限 |

现有数据库密码保留在 `.env`；更改环境变量不会自动修改已初始化 MySQL 的密码。
新部署脚本生成独立随机密码；`.env` 被 Git 忽略。账号表不存密码或登录态。
本轮尚未实现加密 SessionProvider，也不提供保存 QQ 凭据的业务 API。

## 文档与后续阶段

- [最终架构与 ER 设计](docs/architecture.md)：包含尚未交付的最终目标。
- [Phase 1 验收](docs/phase-1-report.md)
- [Phase 2–3 结构与验收](docs/phase-2-report.md)
- [Phase 4–5 结构与验收](docs/phase-4-5-report.md)
- [Phase 6 OneBot Adapter 验收](docs/phase-6-report.md)

后续顺序：Phase 8 真实任务插件 → Phase 9 Vue 管理后台 → Phase 10 部署、压测与完整验收。Phase 6.5 继续等待真实 NapCat；不阻塞已完成的 Phase 7。

## 队列与调度配置

以下变量均可在 `.env` 设置；新部署不填写时使用列出的集中默认值。

| 变量 | 默认值 | 含义 |
| --- | --- | --- |
| TASK_STREAM_NAME / TASK_CONSUMER_GROUP | qq:task:stream / qq-workers | 队列与消费组 |
| TASK_DLQ_NAME | qq:task:dlq | 死信队列 |
| TASK_LOCK_PREFIX / WORKER_KEY_PREFIX | task-lock: / worker: | 命名空间 |
| WORKER_CONCURRENCY | 5 | 单 Worker 并发数 |
| WORKER_HEARTBEAT_INTERVAL / WORKER_HEARTBEAT_TTL | 10 / 60 秒 | 心跳间隔与可见期限 |
| EXECUTION_LEASE_SECONDS / TASK_LOCK_TTL | 60 / 60 秒 | 数据库租约与 Redis 锁 TTL |
| TASK_TIMEOUT_SECONDS | 30 秒 | 单次插件执行期限 |
| WORKER_SHUTDOWN_TIMEOUT | 20 秒 | 优雅退出等待，须小于容器 stop_grace_period |
| MAINTENANCE_INTERVAL | 5 秒 | 恢复与 Outbox 补投周期 |
| OUTBOX_REPUBLISH_SECONDS | 30 秒 | 长期 PENDING 补投间隔 |
| MAX_AUTO_RETRY / AUTO_RETRY_BASE_SECONDS | 2 / 5 秒 | 自动重试上限及指数退避基数 |
| SCHEDULER_ENABLED | true | 是否启用每日投递 |
| SCHEDULE_HOUR / SCHEDULE_MINUTE | 1 / 0 | 每日时间 |
| BUSINESS_TIMEZONE | Asia/Shanghai | 调度与补执行的业务时区 |

生产租约/锁推荐保留默认秒级裕量并保持主机时钟同步。Redis 采用单实例 AOF；
本阶段没有 Redis Cluster/HA 与存储保留期管理。Outbox、执行记录、DLQ 与其索引需后续按审计策略归档。


## Phase 6.5：真实 NapCat 只读联调（等待实例）

状态为 **WAITING_FOR_REAL_NAPCAT / REAL_NAPCAT_NOT_TESTED**，尚未完成真实准出。
已准备 `python -m app.tools.onebot_diagnose --node-id <id> --account-id <id>`，仅调用固定只读 action。
支持 `--wrong-token` 临时错误凭据检查及 `--observe-reconnect --ws-seconds 180` 观察实际停启恢复。
无节点参数时只显示待配置状态，不自动选择账号或访问 NapCat。
普通 pytest 默认跳过 real_onebot 用例；只有显式 `-m real_onebot` 且配置记录 ID 后才运行。

安装、环境变量、账号绑定、网络地址及完整运行命令见 [Phase 6.5 报告](docs/phase-6.5-real-napcat-report.md)。
真实 action 状态见 [兼容矩阵](docs/onebot-compatibility.md)，当前全部 NOT_TESTED。

## Phase 7：Playwright Browser Adapter

通用 Browser 层不包含 QQ 网站规则，不执行任何真实 QQ 业务。Playwright 只出现在 Browser 实现内部与集成测试中；
业务 Task 使用 `context.get_adapter("browser")`，不创建 Chromium 或直接使用 Playwright 对象。

```text
Task → AdapterRegistry → ScopedBrowserAdapter → BrowserAdapter
                                             → BrowserManager（每 Worker 一个 Chromium）
                                             → BrowserSession（独立 BrowserContext）
                                             → BrowserPage
```

Worker 启动时启动 Browser，退出时统一关闭。每个任务作用域结束时回收它创建的所有 Context，即使插件忘记显式关闭。
BrowserManager.startup / shutdown 可重复调用。浏览器崩溃返回统一错误，不自动重放 click / submit 等操作。
一个 Worker 通过 semaphore 限制 Context 总数；超过容量等待，等待受任务超时约束。

任务能力声明沿用按 Adapter 分组的结构：

```python
required_capabilities = {"browser": {"browser.navigation", "browser.click", "browser.storage_state"}}

# 在插件 execute(context) 内：
async with await context.get_adapter("browser").create_session(restore_state=True) as session:
    page = await session.new_page()
    # 通过 BrowserPage 的 goto / click / fill / text / exists / wait_for 等方法操作。
```

Worker 注入的 ScopedBrowserAdapter 已绑定当前账号，不能创建其他账号 Context，也不向任务暴露 Browser 启停接口。
非 Worker 工具可使用 `BrowserAdapter(settings)`，先 `await adapter.start()`，最后 `await adapter.stop()`。
`Selector("css", "#submit")`、`Selector("text", "确定")`、`Selector("role", "button", "确定")` 提供三种选择器。
字符串参数按 Playwright selector 格式处理，普通字符串推荐 CSS。

### 安装与配置

镜像安装 Playwright 所需 Chromium 和 Linux 依赖，不安装 Firefox/WebKit。首次构建会下载浏览器，耗时和镜像体积均高于之前。

```sh
docker compose up -d --build
docker compose exec -T backend python -m app.tools.browser_diagnose
```

本地安装与真实集成测试：

```sh
backend/.venv/bin/python -m pip install -r backend/requirements.lock -e 'backend[test]'
export PLAYWRIGHT_BROWSERS_PATH="$PWD/artifacts/playwright"
backend/.venv/bin/python -m playwright install chromium
backend/.venv/bin/python -m app.tools.browser_diagnose
backend/.venv/bin/python -m pytest backend/tests -m browser_integration -q
```

上述真实 Chromium 测试只访问临时 loopback HTTP 服务，不需要 QQ 或外部网站。
普通 `pytest backend/tests` 默认跳过 browser_integration 和 real_onebot；安装 Python 依赖后不需要下载浏览器即可运行普通测试。
受限桌面沙箱可能禁止 Chromium 创建进程；这时使用 Docker 诊断，或在允许启动浏览器的宿主终端运行。

| 配置 | 默认值 | 含义 |
| --- | --- | --- |
| BROWSER_HEADLESS | true | 无头模式；有头模式需宿主显示环境 |
| BROWSER_TIMEOUT | 5 秒 | 页面动作、选择器、evaluate 等上限 |
| BROWSER_NAVIGATION_TIMEOUT | 15 秒 | 启动与导航上限 |
| BROWSER_MAX_CONTEXTS | 5 | 每个 Worker 的 Context 上限 |
| BROWSER_LOCALE | zh-CN | Context locale |
| BROWSER_TIMEZONE | Asia/Shanghai | Context 时区 |
| BROWSER_USER_AGENT | 未指定 | 可选标准 User-Agent 设置，不提供指纹或反检测功能 |
| BROWSER_STORAGE_KEY | 无默认密钥 | Fernet 密钥，必须保存在 .env 或 secret 环境变量 |
| BROWSER_STATE_DIR | artifacts/browser-state | 本地受控加密状态目录 |
| BROWSER_SCREENSHOT_DIR | artifacts/screenshots | 受控证据目录 |
| WORKER_STOP_GRACE_PERIOD | 60s | Docker 正常停止宽限期 |

所有 Python 配置在 Settings 集中定义。Compose 将状态和截图放 `/srv/artifacts` 的 browser_data 命名卷。
调整任务等待、Context 数量或超时后，应相应增加 Docker 停止宽限期，留出任务清理和关闭 driver 的时间。

### Storage State 与账号隔离

StorageProvider 提供 load / save / delete；当前实现 EncryptedFileStorage。
磁盘只保存 Fernet 认证加密内容，密文内部绑定 account_id，复制 A 的文件给 B 会被拒绝。
目录权限 0700、文件 0600，原子替换防止保存中断留下半文件；加解密与文件 I/O 在线程中执行，不阻塞事件循环。

`session.save_state()` 显式保存；`create_session(restore_state=True)` 显式恢复。没有文件时创建新的未登录上下文。
Cookie、localStorage 和 IndexedDB 可通过 Playwright storage_state 保存；**sessionStorage 不持久化**。
不同账号始终使用独立 Context，已验证 Cookie、localStorage 和 sessionStorage 不互相污染。
同一账号多个并发任务保存时采用最后成功保存者，不合并登录态；需要账号级串行的业务应另加账号级锁。

新部署 `scripts/init_env.py` 自动生成随机存储密钥。现有本地 .env 已补充密钥，未覆盖其他配置、未输出密钥。
密钥缺失或损坏时保存失败，不降级成明文。更换/丢失密钥会导致旧状态无法解密；当前没有 KMS 或自动密钥轮换。
不要将运行文件或密钥提交 Git：`artifacts/`、`*.state.enc`、`playwright/.auth/` 和 `.env` 均被忽略。

### 验证挑战与证据

`session.is_authenticated(predicate)` 由 Task / SiteAdapter 传入网站自己的判断；Browser 层不内置 QQ 登录规则。
网站要求验证码、扫码或设备确认时，Task / SiteAdapter 调用 `session.require_user_action()`，
由 TaskEngine 将 BrowserUserActionRequired 转成 NEED_USER_ACTION。不会自动识别、绕过或点击验证挑战。

截图默认 FAILURE_ONLY，必须同时指定 `failure=True` 和明确的 `safe_selector` 才会截图；只截声明安全的区域，
并强制遮罩 input、textarea、contenteditable 和 data-sensitive 元素。`ScreenshotPolicy.DISABLED` 可完全禁止截图。
通用层不能识别页面所有敏感文字，插件必须确认区域安全，敏感站点应禁用截图；没有默认全页截图。

`context.record_browser_evidence(page.evidence())` 可把非敏感证据加入 TaskResult.data.browser_evidence。
默认 URL 仅保留 origin，去除路径、查询串和 fragment；默认不保存动态标题。截图路径由受控目录和随机名称生成。
不要把 cookies() / evaluate() 返回的登录态放入日志或 TaskResult，TaskResult 继续拒绝敏感字段。

### Worker 与健康

`GET /api/system/health` 增加 browser=UP/DEGRADED/DOWN，来自带 TTL 的 Worker 心跳；后台 API 自身不启动 Chromium。
浏览器不可用时 API/MySQL/Redis 仍可保持 UP；Browser 任务返回明确错误，其他 Adapter 的任务继续执行。
Worker 配置 init=true，Docker PID namespace 在主进程/容器退出时回收子进程。实际验证 SIGTERM 退出码 0，
以及 SIGKILL 后自动重启、重新建立 Chromium。宿主裸进程 SIGKILL 无法执行 finally；生产任务建议在容器中运行。

详见 [Phase 7 验收报告](docs/phase-7-report.md)。

## Phase 8A：只读 Probe 插件

新增诊断插件 `ONEBOT_READONLY_PROBE`、`BROWSER_READONLY_PROBE`、`COMPOSITE_PROBE`。
这些是平台诊断任务，不是 QQ 等级或签到任务。配置、风险、能力、超时和重试规范见 [Task Plugin 开发规范](docs/task-plugin-development.md)，
验收记录见 [Phase 8A 报告](docs/phase-8a-task-plugin-report.md)。

新插件放在 `backend/app/tasks/plugins/`，启动时自动发现；保留 `builtin/` 的已有兼容机制。
GET /api/tasks 返回诊断、只读、风险级别、版本、能力和重试策略元数据，无新增表或迁移。
三个 Probe 默认不参与每日 Scheduler；账号配置仍须显式启用。

通过现有 API 使用：

1. POST /api/tasks 登记对应 task_code（若尚未登记）。
2. PUT /api/accounts/{id}/tasks/{code} 写入 `enabled=true` 和 `config_json`。
3. POST /api/tasks/{code}/execute，请求体 `{"account_id": 1}`，返回 202 与 execution_id。
4. GET /api/executions/{execution_id} 查看终态及 result_json。

OneBot Probe 配置是 `{}`，账号必须绑定真实且身份一致的 OneBot Node。
Browser 和 Composite 配置例如：

```json
{
  "url": "http://127.0.0.1:8765/simple",
  "selector": "h1",
  "expected_title": "Browser fixture",
  "expected_text": "Local fixture"
}
```

地址指 **Worker 内可达的受控测试站点**；不会自动启动该示例端口。
当前 URL 限定本机测试路径，不读取外部网站或恢复登录态。只保存已知标题、origin 和验证结果，不保存任意正文。
可直接运行完整验收工具，它会自动启动临时测试站点并清理临时账号：

```sh
backend/.venv/bin/python scripts/e2e_probe.py
```

该工具需要一个 Docker Worker 和已配置的 .env。Composite 的真实 Chromium pytest 使用 Fake OneBot；
真实 OneBot Task 和 Real OneBot + Real Browser 仍待 Phase 6.5，明确标记 REAL_ONEBOT_TASK_NOT_TESTED。

## Phase 8B-1：QQ 只读业务任务

本阶段提供真实业务语义的查询插件，尚未验证真实 NapCat。它们与 Probe 区分：
`category=QQ_ACCOUNT`、`diagnostic_only=false`、`scheduled=false`，均为幂等只读、SAFE_READONLY、NONE 副作用。
任务默认不进入每日 Scheduler，必须手工启用账号配置后触发。

| task_code | config_json | data |
| --- | --- | --- |
| QQ_ACCOUNT_STATUS | `{}` | 脱敏 QQ、昵称（最多 128 字符）、online、good、connection_state |
| QQ_FRIEND_SUMMARY | `{"include_category_counts": false}` | friend_count；开启选项后增加 remark_count/nickname_count |
| QQ_GROUP_SUMMARY | `{"include_role_counts": false}` | group_count；开启选项时明确 role_counts_supported=false，角色数量为 null |
| QQ_RUNTIME_STATUS | `{"execution_history_hours": 24}` | 当前账号、Node 最近记录状态、OneBot 在线状态、当前执行租约状态、最近成功/失败执行摘要 |

配置禁止额外字段并严格校验类型；历史时间窗允许 1–168 小时。
好友/群明细不返回、不写入 Execution、不写日志；不为角色统计逐群调用详情接口。
Runtime 只读 Service 固定绑定当前账号，SQL 留在 Repository，不查询全局 Worker 或其他账号。
`worker_status=LEASE_ACTIVE` 表示当前执行的数据库租约有效，不代表独立的全局 Worker 健康探测。
运行状态查询成功时 onebot_status 仍可能为 OFFLINE/DEGRADED；这表示成功取得异常状态，不表示 QQ 在线。

业务插件把只读网络重试预算交给 Worker：OneBot 每次 RPC 一次尝试，连接/超时错误再由既有次数和退避策略创建新 RETRY 记录。
默认最多自动重试 2 次；身份不匹配、离线、认证错误、业务校验失败和整个任务超时不重试。
原 Probe/普通 Adapter 使用方式保留内部短重试，耗尽后不叠加 Worker 重试。

通过已有 POST /api/tasks 登记四个代码，然后 PUT /api/accounts/{id}/tasks/{code} 启用配置，
POST /api/tasks/{code}/execute 提交 `{"account_id": 1}`，得到 202 后 GET /api/executions/{execution_id} 查询结果。
真实执行需本人 QQ Account 绑定已配置的 OneBot Node；未配置时明确失败，不会自动替换成 Fake。

完整开发验收（FakeOneBot + 真实 HTTP、MySQL、Redis、Worker）：

```sh
docker compose up -d --build
backend/.venv/bin/python scripts/e2e_business.py
```

此工具使用同一 API 工厂在容器内启动临时 loopback HTTP 服务，并运行真实 Worker.run，使用独立 Stream 和只发布验收账号的 Outbox。
由于共用 MySQL Outbox，包装脚本短暂停止常驻 Worker/Scheduler，finally 恢复原先运行的服务；请用于开发验收环境。
FakeOneBot 只在验收工具中显式注入，不存在生产 Worker 的 Fake 开关。工具创建缺少的四个 TaskDefinition、临时账号和执行，
结束后软删除临时账号、清理自己的 Redis key、关闭临时 API，保留执行审计和任务定义。
测试结果中的好友 19、群 7 是 Fake fixture 数量，不是真实 QQ 数据。

```sh
backend/.venv/bin/python -m pytest backend/tests -q
# 只有完成真实 NapCat 配置后才显式运行；替换为本人账号 ID。
REAL_ONEBOT_ACCOUNT_ID=1 backend/.venv/bin/python -m pytest backend/tests -m real_onebot_business -q
```

当前明确为 **REAL_ONEBOT_BUSINESS_NOT_TESTED**。详见 [Phase 8B-1 报告](docs/phase-8b1-readonly-business-task-report.md)。

## Phase 8B-2：QQ Web 只读业务任务

已建立 `Task → QQWebSiteAdapter → BrowserAdapter → Playwright` 分层，新增：

| Task | 能力 | 超时 |
| --- | --- | --- |
| QQ_WEB_LOGIN_STATUS | 登录状态检查 | 20 秒 |
| QQ_WEB_PAGE_STATUS | 受控页面状态 | 20 秒 |
| QQ_TASK_CENTER_SUMMARY | 任务状态摘要 | 30 秒 |
| QQ_ACTIVITY_SUMMARY | 活动数量摘要 | 30 秒 |

全部为 QQ_WEB / BUSINESS / SAFE_READONLY，read_only、idempotent 为 true，副作用 NONE，scheduled=false，版本 1.0.0。不签到、不领取、不兑换、不提交。

页面状态和登录状态配置 `{"page_key":"PROFILE"}`，可选 TASK_CENTER、ACTIVITY_CENTER；两个摘要任务配置 `{}`。不接受任意 URL。环境字段 QQ_WEB_BASE_URL、QQ_TASK_CENTER_URL、QQ_ACTIVITY_URL 默认留空。**真实 URL 和页面规则尚未核验，生产执行返回 SITE_NOT_CONFIGURED；仅填写环境变量不会启用真实页面。**

Site 按账号恢复已有加密 Browser Storage State。无可用状态、身份不匹配、二维码/验证码/设备验证或未知登录状态返回 NEED_USER_ACTION；不会自动登录。新 Web 任务全部禁用截图，执行记录不保存 HTML、Cookie 或 Storage。

真实 Chromium + 本地 Fixture 的 HTTP API → Outbox → Redis → Worker → MySQL 链路已验收。真实 QQ Web 状态为 **REAL_QQ_WEB_NOT_TESTED**，不能将 Fixture 成功解释为真实 QQ 成功。

详见 [Site Adapter 开发规范](docs/site-adapter-development.md) 和 [Phase 8B-2 验收报告](docs/phase-8b2-web-readonly-task-report.md)。Docker 开发环境可运行 `backend/.venv/bin/python scripts/e2e_web.py` 复验；工具会暂时停止并恢复 Worker/Scheduler。

## Phase 8C：Executor Router 与 Capability Matrix

新增 Operation / CapabilityResolver / ExecutorRouter / RiskPolicy。新业务插件通过 `context.get_service("executor_router").resolve(operation, context)` 查询执行器；本阶段只 resolve，没有执行写操作。现有 Task 保持兼容，Router 尚未作为旧执行 API 的全局门禁。

管理 API：`GET /api/accounts/{id}/capabilities`，可选 `?mode=DIAGNOSTIC`，沿用管理鉴权。响应区分综合 status、runtime_status、verification_level 和候选原因，不返回凭据、登录态内容或内部队列信息。

**当前 Router 允许生产选择的 QQ Operation 为 0 项。** Chromium 基础设施是真实验证；OneBot 业务是 MOCK_ONLY；QQ Web 业务是 FIXTURE_VERIFIED；真实 QQ Web/NapCat 未验证。DIAGNOSTIC 不会降低门槛。Mobile 仅接口和 Fake，无真实设备实现。

每项 Operation 的执行器优先级可通过 `EXECUTOR_PRIORITIES` JSON 配置；不能改变验证等级。人工验证和缺失认证不允许跨执行器自动切换，HIGH_SIDE_EFFECT 不开放执行或 fallback。

参见 [Router 开发规范](docs/executor-router.md)、[QQ 能力矩阵](docs/qq-capability-matrix.md)、[Phase 8C 报告](docs/phase-8c-executor-router-report.md)。

## Phase 8D：真实环境验收（等待前置条件）

当前 **8D-A=WAITING_FOR_REAL_NAPCAT**、**8D-B=WAITING_FOR_REAL_QQ_WEB_LOGIN**。Node 数量为 0，真实 QQ Web URL 和加密登录态均未配置。生产可选 QQ Operation 仍为 0，未升级任何验证等级。

两块可以独立准备。NapCat 需要用户完成登录、启用 HTTP/WS/heartbeat，在本地配置凭据引用并绑定 Node/Account；QQ Web 需要实际页面 URL、目标账号和人工登录。不要把 Token、Cookie、明文 Storage State 或 QR 发到聊天。

已有 OneBot 前置只读诊断入口：`python -m app.tools.onebot_diagnose --node-id <NODE_ID> --account-id <ACCOUNT_ID>`。`pytest -m real_onebot` 只在显式选择且具备真实 ID 时运行；普通 pytest 不访问真实 QQ。

旧 `real_onebot_business` 用例尚未覆盖 Router，因此不能作为 Phase 8D 业务准出；需先接入 Router 再验收。真实 Web Inspection/Profile/人工登录采集和 `real_qq_web` 用例仍待目标确认后完成。当前不提供伪造真实结果或自动登录的替代路径。

详见 [真实环境验收报告与待办](docs/phase-8d-real-environment-report.md)。本阶段未完成，不自动进入下一阶段。

## 本地 Git 基线

真实环境联调前已初始化本地 Git 仓库，基线提交消息为 `baseline before real environment integration`。仅保存本地代码，不配置远程仓库或自动推送。

`.gitignore` 排除本地环境文件、加密浏览器状态、runtime/artifacts、截图、日志及常见凭据文件，保留 `.env.example`。首次提交前检查全部候选文件中的当前凭据精确匹配和私钥头，并验证忽略规则。后续仍需审查新增文件，不能仅依赖文件名忽略来保证无凭据。

Phase 8D 预检报告中的“尚未初始化 Git”描述是当时状态；此后已建立本地基线。真实 NapCat / QQ Web 验证等级不因此改变。
