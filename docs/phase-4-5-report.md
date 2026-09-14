# Phase 4–5：Queue、Worker、Lease、Retry 与 Scheduler

## 完成内容

按本轮要求先复验：阅读 AGENTS、README、Phase 2 报告及现有 Engine/Repository；
原 73 项 pytest、Ruff、Alembic current/check 均通过。目录尚未初始化 Git，无法提供 Git diff。
本轮没有开发前端、真实 QQ 任务、Playwright 或 WebSocket。

采用 Redis Stream，打通 API → Execution/Outbox → Redis → Worker → TaskEngine → DB → ACK。
新增四个无外部调用的 Mock 插件用于真实验收；没有把任何模拟结果表述为真实账号操作成功。

## 架构设计

API 仍遵守 API → Service → Repository。DispatchService 在同一事务中预占账号/任务执行位、
保存 PENDING execution 与 TaskOutbox。API 返回 202 后，独立 Worker/Scheduler 维护循环负责投递。
Redis 不可用不会丢失已接受请求；数据库不可用则请求失败，不返回虚假受理结果。

Outbox 发布成功后记录 published_at；若发布后进程崩溃，允许再次投递。
已发布但长期 PENDING 也会补投，防止 Redis AOF 最后短暂数据丢失造成记录永久挂起。
消息传输至少一次，业务开始和终态使用数据库条件更新去重。

TaskQueue Protocol 隔离 Redis，统一 TaskJob 字段，不发送 ORM 或账号凭据。
Worker 领取既有 execution，调用 TaskEngine.run，不调用会创建第二条 execution 的兼容 execute 方法。
Service 统一校验状态机，Repository 完成 CAS 和持久化。

## 修改文件

| 分组 | 文件 |
| --- | --- |
| Queue | backend/app/queue/{base,redis_stream,lock,factory,__init__}.py |
| 数据模型 | backend/app/models/task_execution.py、task_outbox.py、__init__.py |
| 持久化 | backend/app/repositories/dispatch.py、backend/app/services/unit_of_work.py |
| 服务 | backend/app/services/dispatch.py、execution_state.py、worker_status.py |
| Worker | backend/app/workers/worker.py、heartbeat.py |
| Scheduler | backend/app/scheduler/scheduler.py |
| API | backend/app/api/dispatch.py、backend/app/main.py、schemas/management.py、schemas/system.py |
| Engine/Mock | backend/app/tasks/engine.py、base.py、builtin/mock_success.py、mock_fail.py、mock_timeout.py、mock_user_action.py |
| 配置/日志 | backend/app/core/config.py、logging.py、.env.example |
| 迁移 | backend/alembic/versions/c888eb342135_queue_lease.py |
| 测试 | backend/tests/test_queue.py、test_dispatch_worker.py、test_dispatch_api.py、test_redis_failure.py、conftest.py、test_migration.py |
| 部署/文档 | docker-compose.yml、backend/pyproject.toml、requirements.lock、README.md、frontend/README.md（阶段说明）、本报告、scripts/e2e_queue.py |

## 数据库变化

迁移链：`733e680fde79 → c888eb342135`。

`task_execution` 新增：

- parent_execution_id：自关联外键、唯一；每个父执行最多一个直接重试子节点。
- business_date：业务日期；旧记录保持 NULL，补执行查询按配置时区的创建时间区间兼容。
- schedule_key：可空唯一键，值为 account_id:task_code:business_date:daily。
- worker_id、lease_token、lease_until、heartbeat_at：执行持有者和租约。
- dlq_at：死信归档时间。
- 索引 `(status, lease_until)`：加速过期执行扫描。

`task_outbox`：id、execution_id（唯一 FK）、job_id（唯一）、available_at（索引）、published_at、attempt_count。
available_at 同时支持延迟自动重试，不用 Worker 阻塞等待退避。
凭据不存入上述字段或消息；lease_token 只是内部所有权标识，不通过 API 或日志返回。

## Redis Stream 设计

| Key | 用途 |
| --- | --- |
| qq:task:stream | TaskJob JSON 消息；消费者组 qq-workers |
| qq:task:dlq | 无效、无法恢复或重试耗尽的消息 |
| qq:task:dlq:index | 按 execution/error 或畸形摘要去重 |
| task-lock:{account_id}:{task_code} | 所有者值、TTL、Lua 比较续租/删除 |
| worker:{worker_id} | started_at、last_heartbeat、status、active_execution，带 TTL |

Worker 启动/消费前确保消费组存在；XREADGROUP 获取新消息，XAUTOCLAIM 接管长期 Pending。
活跃执行即使消息被接管，也不能绕过数据库 RUNNING/租约检查重新执行。
结果提交后 XACK；本队列限定一个逻辑消费组，ACK 后 XDEL 清理。
不自动裁剪未处理消息，不以简单 List 或 BRPOP 实现。

DLQ 保存已验证的原 TaskJob、固定错误码、时间、worker_id；畸形载荷可能带凭据，
因此只保存 SHA-256 摘要。DLQ 写入、Pending ACK、删除为一个 Lua 原子操作，并带幂等索引。

## 状态机

- PENDING → RUNNING。
- PENDING → SKIPPED：消费前账号/任务被关闭。
- RUNNING → SUCCESS / FAILED / SKIPPED / NEED_USER_ACTION。
- SUCCESS、FAILED 等终态不能返回 RUNNING。
- 重试不是 FAILED → PENDING 原地修改，而是创建新的 PENDING 子记录。

ExecutionStateMachine 校验允许转换；Repository 更新语句还包含预期状态，防止并发写覆盖。
业务明确失败、未实现、人工处理与真正成功分别保留，异常不会变成成功。

## Lock 与 Lease

API 创建 PENDING 时就占用 TaskConfig.active_execution_id，拒绝重复排队。
Worker 取得 Redis 锁后 CAS 领取 execution，写入 worker_id 和租约所有权。
长任务按锁/租约最短 TTL 的三分之一续期。Redis 锁续期失败则停止插件并拒绝写回结果。
终态提交需要 worker_id、lease_token 匹配，且租约未到期。

旧持有者不能释放后来取得的 Redis 锁，也不能覆盖已恢复的数据库执行记录。
进程消失时 Redis 锁通过 TTL 释放；数据库占用由 Recovery 释放。

Worker SIGTERM/SIGINT 停止取新任务，已有任务在退出宽限期内可完成；超时取消协程，
保留 RUNNING/Pending，交给租约恢复。请求关闭过程中 dequeue 刚返回的消息也不会被新启动。
SIGKILL 不依赖 finally，恢复依赖数据库租约。

## Retry 与 Recovery

手工补执行按业务日期和可选账号筛选最新失败叶节点；排除停用账号/任务、已有活跃执行、
同日成功，以及后续记录已经变为其他状态的任务。查询按主键分页，不默默只处理前 1000 条。
父节点唯一约束和原子占用共同防止重复点击或多个进程重复生成子记录。

自动重试需要同时满足：ADAPTER_TIMEOUT 或 ADAPTER_CONNECTION_ERROR、插件 retry_safe=True、
retry_count 小于 MAX_AUTO_RETRY。默认最多 2 次，延迟 5、15 秒，支持注入时钟测试。
业务失败、人工处理、任务整体超时、账号配置错误、Worker 租约过期不会自动重试。
超限或插件已不可用的消息进入 DLQ。手工补执行保留累计计数，不重新打开自动无限重试。

Worker/Scheduler 都可运行维护，使用 CAS 保证多维护者安全。
过期 RUNNING → FAILED / WORKER_LEASE_EXPIRED，保留原开始时间和审计关联，释放执行占用。
旧版无租约 RUNNING 超过兼容超时同样可恢复。恢复不自动执行外部操作。

## API 变化

- POST /api/tasks/{task_code}/execute：`{"account_id": 1}`，返回 HTTP 202 + PENDING 执行详情。
- POST /api/executions/retry-failed：空体或可选 account_id/date，返回 created、skipped、execution_ids。
- GET /api/system/worker-status：Worker 状态，不暴露 Redis key、租约 token 或配置凭据。
- execution 查询新增 parent_execution_id、business_date、worker_id、lease_until、heartbeat_at。
- health 新增 api=UP，仍按 MySQL/Redis 判断核心可用性，NapCat 未启动不影响核心状态。

上述管理入口延续 Bearer 鉴权。202 表示持久化受理；Redis 不可用或 Worker 不在线时可以保持 PENDING。

## Scheduler 实现

独立 `python -m app.scheduler.scheduler`，APScheduler 3.x AsyncIOScheduler。
默认 Asia/Shanghai 每日 01:00；时区、时、分均来自配置。
schedule_key 的数据库唯一约束保证同一天同槽位最多一条调度记录，多实例并行仍可去重。
每日调度与恢复/Outbox 维护分开；关闭每日调度不关闭恢复。
Scheduler 不实例化或调用 TaskEngine，不执行 Task 插件。

## 测试结果

最终完整 pytest：**108 passed**。原有 73 项继续通过，新增 35 项；两条原有第三方 TestClient 弃用警告。
Ruff：All checks passed。

覆盖真实 Redis 的 enqueue/dequeue/ACK、Pending reclaim、序列化、DLQ、锁 token 保护和 TTL；
Worker 四类终态、失败后继续、异常隔离、长任务续租、重复消息、并发调度去重、租约过期、
过期 Worker 写回拒绝、心跳超时、退出期间停止领取、强制取消后恢复；
新重试父子链、禁用/成功/运行中排除、旧日期兼容、自动次数上限、无真实等待的退避时钟；
API 202、Redis 真实连接失败与 Outbox 保留、Scheduler 配置及开关。

迁移验证：

- MySQL 8 upgrade head 成功，current=c888eb342135，alembic check 无漂移。
- 临时 SQLite：upgrade head → check → downgrade 733e680fde79 → upgrade head → check，
  另验证全量 downgrade base / upgrade head。没有回退或清空用户真实数据库。

## Docker 与真实联调

- Compose 配置通过，镜像构建和 migrate 服务成功；backend、worker、scheduler、mysql、redis 正常启动。
- `scripts/e2e_queue.py` 实际通过：MockSuccess SUCCESS、MockFail FAILED、MockNeedUserAction NEED_USER_ACTION。
- retry-failed 创建新的子 execution，子记录被 Worker 消费，原 FAILED 保持不变。
- 对运行 MockTimeout 的真实 Worker 容器发送 SIGKILL；等待真实 TTL，Scheduler 将其标记
  FAILED / WORKER_LEASE_EXPIRED，验收脚本恢复 Worker。
- 扩容两个真实 Worker，12 个 MockSuccess 执行全部 SUCCESS，实际分配到两个不同 worker_id。
- 所有验收临时账号软删除，执行记录保留；未连接 QQ。

## 已知问题与边界

- 单 Redis 实例，不提供 Redis Cluster/HA；任务消息只面向一个消费组。
- 需要主机时钟同步，生产保留合理秒级 TTL。插件必须遵守异步取消协议。
- 外部操作不保证 exactly-once；租约过期后人工补执行前应核对外部状态。
- DLQ、执行历史、Outbox、DLQ 幂等索引尚无自动归档/保留期任务，应在压测和部署阶段补齐。
- Scheduler 不自动补建整个进程离线期间错过的每日调度，也未提供 Cron UI。
- Worker 容器健康检查验证进程存活；业务在线状态以带 TTL 的 worker-status 为准。

这些是当前部署/扩展边界；本轮列出的测试、迁移、真实 Stream、重试及 SIGKILL 恢复均已验证。

## 尚未完成

按用户调整后的顺序：Phase 6 完整 NapCat Adapter，Phase 7 Playwright，Phase 8 真实任务插件，
Phase 9 Vue3 管理后台，Phase 10 HA/归档/压测和完整部署验收。

## 官方接口依据

- [Redis Streams](https://redis.io/docs/latest/develop/data-types/streams/)
- [XAUTOCLAIM](https://redis.io/docs/latest/commands/xautoclaim/)
- [APScheduler AsyncIOScheduler](https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/asyncio.html)
