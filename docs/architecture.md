# 最终架构与数据库设计

本文是后续各阶段的实现契约。Phase 1 仅实现基础服务，不代表本文所有功能已交付。

## 分层及进程

| 层/进程 | 责任 | 约束 |
| --- | --- | --- |
| Vue 前端 + Nginx | 管理账号、开关、触发任务、查看日志；同源代理 /api | 不接触第三方凭据 |
| FastAPI API | 参数校验、鉴权、响应映射 | 不直接访问数据库 |
| Service | 业务规则、事务边界、任务投递、人工恢复 | 通过 Repository 持久化 |
| Repository | SQLAlchemy 查询与写入 | 不调用插件和第三方 API |
| Scheduler 独立进程 | APScheduler 按业务时区每天投递启用任务 | 不执行任务；未来替换为 Beat |
| Queue + Outbox dispatcher | Redis Stream 消费组；数据库事件可靠投递 | Queue Protocol 屏蔽 Redis，未来替换为 Celery |
| Worker 多实例 | 领取、续租、执行、提交结果、ACK、心跳 | 与 API 解耦，异常不退出消费循环 |
| Task Engine | 校验状态、AccountContext、超时、结果归一化 | 根据 registry 查找 task_code |
| Task Plugin | BaseTask.execute/check_status | 不依赖 Request、SQL、NapCat、Playwright |
| Adapter | OneBot、Browser、Mobile 与 Session Provider | 封装第三方调用及异常，不侵入业务层 |

API 和 Scheduler 共用投递服务。事务中创建 PENDING execution 与 outbox；后台 dispatcher
投递到 Stream，成功后标记 outbox。允许重复投递，Worker 根据 execution_id 和状态条件更新去重。
消费组 ACK 在结果提交之后；Worker 崩溃的消息通过超时 claim 恢复。

锁使用带随机 token 的 SET NX PX，并用 Lua 比较 token 后续租/删除。执行中持续续租。
每日锁 `task-lock:{account_id}:{task_code}:{business_date}` 配合不含日期的执行锁，避免跨午夜并发。
数据库 task_run_guard 唯一键作为第二道并发保护；锁丢失后不接受旧 Worker 的结果写入。
外部副作用不能保证 exactly-once，插件需要供应商幂等键或状态核验；结果不确定时要求人工核对，
不能自动重放发消息、发布内容等非幂等动作。

## 目录

```text
backend/
  app/
    main.py
    api/              # HTTP 路由
    core/             # 配置、连接、日志
    models/           # Phase 2 SQLAlchemy 模型
    schemas/          # API DTO
    repositories/     # 持久化边界
    services/         # 业务服务、事务
    tasks/            # Phase 3 base、registry、engine、builtin/
    adapters/         # Phase 6/7 onebot/、browser/、mobile/
    scheduler/        # Phase 5 独立调度进程
    workers/          # Phase 4 消费者
  alembic/            # Phase 2 migration
  tests/
  pyproject.toml
  requirements.lock
  Dockerfile
frontend/             # Phase 8 Vue 应用
docs/
docker-compose.yml
.env.example
```

测试归入 backend/tests，便于独立构建和 CI。新增 docs 保存架构及验收记录；
后续新增 queue 模块隔离传输实现，新增 outbox 解决数据库和 Redis 的双写一致性。
空包只预留分层边界，没有虚假 Worker 或任务成功实现。

## ER 关系

| 父实体 | 关系 | 子实体 | 删除策略 |
| --- | --- | --- | --- |
| node | 1:N | account.node_id | 节点删除置空；账号先禁用 |
| account | 1:N | account_session.account_id | 会话撤销、密文清理 |
| account | 1:N | task_config.account_id | 软删除账号，保留历史 |
| task_definition | 1:N | task_config.task_code | 任务定义停用，不删除 |
| account | 1:N | task_execution.account_id | 保留审计记录 |
| task_definition | 1:N | task_execution.task_code | 保留定义 |
| task_execution | 1:N | execution_log.execution_id | 按保留策略清理 |
| task_execution | 1:1 | task_outbox.execution_id | 投递后保留审计 |
| task_execution | 1:N | task_execution.parent_execution_id | 重试关联原记录 |
| account + task_definition | 1:N | task_run_guard | 按业务日期唯一 |

## 表字段（Phase 2 实现）

统一 BIGINT 主键，时间使用 UTC DATETIME(6)，API 返回含时区 ISO 8601。
业务日期按配置时区（默认 Asia/Shanghai）计算；查询当天使用 UTC 半开时间区间，避免数据库时区偏差。
JSON 仅保存非敏感任务参数/结果。状态使用字符串与应用枚举，便于扩展。

| 表 | 主要字段与约束 |
| --- | --- |
| account | id, account_no VARCHAR(128), nickname, platform, status, online_status, online_checked_at, node_id nullable, created_at, updated_at, deleted_at；UNIQUE(platform, account_no) |
| account_session | id, account_id FK, provider, encrypted_payload, key_version, expires_at, revoked_at, created_at, updated_at；业务表不保存密码/Token/Cookie |
| node | id, name, adapter_type, endpoint, credential_ref, status, last_seen_at, created_at, updated_at；endpoint 由管理员配置 |
| task_definition | id, task_code UNIQUE, task_name, description, category, default_enabled, executor_type, status, created_at, updated_at |
| task_config | id, account_id FK, task_code FK, enabled, config_json, created_at, updated_at；UNIQUE(account_id, task_code) |
| task_execution | id, execution_id UUID UNIQUE, account_id FK, task_code FK, trigger_type, status, retry_count, parent_execution_id nullable FK, business_date, start_time, end_time, result_json, error_code, error_message, created_at；INDEX(business_date,status), INDEX(account_id,task_code,created_at) |
| task_outbox | id, execution_id FK UNIQUE, payload_json, published_at nullable, attempt_count, next_attempt_at, created_at；INDEX(published_at,next_attempt_at) |
| task_run_guard | id, account_id FK, task_code FK, business_date, active_execution_id, lease_token, lease_until, success_execution_id；UNIQUE(account_id,task_code,business_date) |
| execution_log | id, execution_id FK, level, event_code, safe_message, created_at；INDEX(execution_id,created_at) |

Worker 心跳存在 Redis 带 TTL 的 key 中，node 表用于账号接入节点，两者不混用。
在线状态只能来自 Adapter 的最近真实检测，过期则 UNKNOWN，任务开关不能改变在线状态。

## 执行规则

状态统一为 PENDING、RUNNING、SUCCESS、FAILED、SKIPPED、NEED_USER_ACTION。
trigger_type 为 SCHEDULE、MANUAL、RETRY、API。TaskResult 包含 success、status、message、data、
error_code、start_time、end_time；成功布尔值与状态必须一致。

执行前重新检查账号有效性和配置开关，禁用后尚未运行的任务标记 SKIPPED。
未实现任务返回 SKIPPED + NOT_IMPLEMENTED；验证码/设备验证返回 NEED_USER_ACTION。
PC_ONLINE 第一版仅检测真实连接及登录账号匹配，不能宣称保持在线或获得任何权益。

一键补执行按账号/任务分组查询当天 FAILED，排除禁用、当天已成功、已有 PENDING/RUNNING、
最新一次为 NEED_USER_ACTION 的项目；在事务和 guard 保护下新建 RETRY 记录，保留原始失败。
重复点击返回已排队/跳过数量；不能将历史失败原地改为成功。

## 敏感数据与扩展

会话使用独立 SessionProvider。生产用 KMS/Vault 管理密钥；本地使用注入的加密主密钥，
密文存 account_session，支持 key_version 轮换。密钥不入库、不入镜像、不入 Git。
截图和浏览器 storage_state 也视为凭据，以私有存储和过期策略管理。
管理接口鉴权在业务 CRUD 阶段加入，部署前必须验收；Phase 1 仅绑定 localhost。
Adapter 目标限定管理员配置的节点/域名，防止任意 URL 的内部网络访问。

新 Task 放入 tasks/builtin 单独文件，继承 BaseTask 并注册，声明配置 schema 与 adapter 能力。
新 Adapter 实现能力 Protocol，通过工厂注入 AccountContext；插件只调用能力接口。
OneBot 仅对幂等查询退避重试；WebSocket 负责事件监听、重连和账号状态更新。
BrowserAdapter 在 Worker 内统一管理浏览器，每个账号独立 context，任务结束清理 page/context。
Mobile 第一阶段只保留接口。所有 Adapter 测试使用 mock，不访问 QQ。

## 官方接口依据

- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
- [SQLAlchemy 异步连接与会话](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Redis 异步客户端与连接清理](https://redis.io/docs/latest/develop/clients/redis-py/async/)
