# Phase 2、Task Engine 与 OneBot 交付报告

日期：2026-09-11。本轮按用户要求先创建根目录 AGENTS.md，再复验 Phase 1，分阶段实现与测试。

## Phase 1 复验

- 原有 13 项测试通过，Compose 配置通过，运行服务健康接口正常。
- 检查 `.env` 已存在且必填值有效，校验过程不输出值。
- 修复配置类和 Compose 中的开发密码回退；DATABASE_URL 改为必填。
- `.env.example` 不再包含可用密码，新增不覆盖已有配置的随机凭据初始化脚本。
- 原有数据库卷及本机 `.env` 密码保留，没有执行密码重置或数据卷清空。

## 修改文件

| 分组 | 文件 |
| --- | --- |
| 项目规则 | AGENTS.md，按用户原文创建，Markdown 转义还原为正常标识符 |
| 配置和安全 | backend/app/core/config.py、errors.py、security.py |
| 数据模型 | backend/app/models/account.py、node.py、task_definition.py、task_config.py、task_execution.py、common.py、__init__.py |
| 持久化 | backend/app/repositories/management.py、runtime.py |
| 服务 | backend/app/services/unit_of_work.py、management.py、task_runtime.py |
| Schema/API | backend/app/schemas/management.py、backend/app/api/management.py、backend/app/main.py |
| 迁移 | backend/alembic.ini、backend/alembic/env.py、script.py.mako、versions/733e680fde79_initial_schema.py |
| 插件核心 | backend/app/tasks/base.py、registry.py、engine.py、bootstrap.py、builtin/__init__.py、builtin/not_implemented.py |
| OneBot | backend/app/adapters/errors.py、onebot/__init__.py、onebot/client.py |
| 测试 | backend/tests/conftest.py、test_database.py、test_management_api.py、test_migration.py、test_task_engine.py、test_onebot.py、test_env_setup.py |
| 运行部署 | backend/pyproject.toml、requirements.lock、Dockerfile、docker-compose.yml、.env.example、scripts/init_env.py |
| 文档 | README.md、本报告 |

本机 `.env` 新增 DOCKER_DATABASE_URL 和随机 ADMIN_ACCESS_TOKEN；不纳入版本控制、不输出到报告。

## 数据库结构

已在真实 MySQL 上执行首个迁移 `733e680fde79`，`alembic check` 确认没有模型漂移。

| 表 | 字段及约束 |
| --- | --- |
| node | id PK、name UNIQUE、adapter_type、status、created_at、updated_at |
| account | id PK、account_no、nickname、platform、status、online_status、node_id FK→node.id、deleted_at、created_at、updated_at；UNIQUE(platform,account_no) |
| task_definition | id PK、task_code UNIQUE、task_name、description、category、default_enabled、executor_type、status、created_at、updated_at |
| task_config | id PK、account_id FK→account.id、task_code FK→task_definition.task_code、enabled、config_json、active_execution_id、created_at、updated_at；UNIQUE(account_id,task_code) |
| task_execution | id PK、execution_id UNIQUE、account_id FK、task_code FK、trigger_type、status、retry_count、start_time、end_time、result_json、error_code、error_message、created_at；retry_count >= 0 |
| alembic_version | 当前迁移版本 |

执行查询索引为 `(created_at,status)` 和 `(account_id,task_code,created_at)`。
账号软删除保留审计，运行中的账号拒绝删除；外键保护关联一致性。
数据库时间为 UTC，ORM 读取恢复时区，API 返回带时区时间。
模型不保存 QQ 密码、Cookie 或登录态；节点目前只作管理标签，外部地址由环境变量配置。

## 架构与行为

API 仅调用 ManagementService，不导入 SQLAlchemy 或操作 Session。
Service 通过 UnitOfWork 组织事务，Repository 负责查询、写入及原子占用。
SQLAlchemy 异常转换为 BusinessError，日志只记录安全事件名和错误码。

TaskEngine 使用可替换的 TaskStore Protocol；Registry 注册类、检查重复 task_code 和 async 接口。
bootstrap 自动发现 builtin 目录中的独立插件文件。TaskContext 只提供账号快照、配置和 Adapter。
未找到插件/账号、禁用、超时、重复执行、Adapter 异常、插件异常、非法结果和持久化失败有独立错误码。
已启动执行保存为 RUNNING，再保存终态；未通过预检查的请求只返回结果，不创建伪执行记录。
TaskResult 校验终态、success 一致性、时间和敏感字段名。日志不输出插件异常原文。

数据库占用和 RUNNING 记录在同一事务创建；完成结果和释放占用在同一事务提交。
错误持有者无法释放别人的占用。异步取消会标记失败并清理占用，随后传播 CancelledError。
持久化失败不返回成功。外部副作用不保证 exactly-once，非幂等操作不可盲目重试。

OneBot 通过 httpx.AsyncClient 封装 get_status/get_login_info；离线、超时和响应错误使用三个 Adapter 异常。
登录信息调用先做在线检测。连接与超时有有界重试；HTTP 错误、JSON/结构错误不重试。
测试用 MockTransport，未连接真实 QQ。WS URL 仅为配置预留，没有宣称实现事件监听。

## API 变化

新增 14 条管理路由，详见 README 表格：账号 CRUD、配置查询/单项更新/批量开关、
任务定义查询/创建、节点查询/创建、执行记录列表/详情。
管理接口统一 Bearer 鉴权，未配置凭据关闭管理入口。
新增请求校验错误格式，避免回显请求体中的误传敏感字段。
公开健康探针保持原行为。

## 测试结果

- Phase 1 基线：13 passed。
- Phase 2：22 passed；含数据库唯一/外键约束、软删除、事务回滚、配置更新、API 与鉴权、迁移升降级。
- Engine 首轮：43 passed；后续补充并发竞争、缺失定义/配置、插件约束、bootstrap 清理。
- 本轮完整回归：**73 passed**，两条已有第三方 TestClient 弃用警告，无测试失败。
- Ruff：全部通过。
- Compose：配置校验、镜像构建与启动通过；migrate 成功退出，三个常驻服务 healthy。
- 真实 MySQL：迁移与 `alembic check` 通过。
- 真实 HTTP + MySQL + Engine 联调：创建账号、配置开关、执行占位插件、读取 SKIPPED 记录、软删除通过。
  临时验收账号已软删除，执行记录按审计设计保留；新增 NOT_IMPLEMENTED 定义供框架验证使用。

## 尚未完成

- Redis Queue / Worker / Outbox、分布式租约续期、强制退出后的人工恢复入口与自动恢复策略。
- 每日成功去重、retry-failed、HTTP 手动任务投递；当前 Engine 为独立可调用核心，不在 API 内直接执行任务。
- APScheduler、WebSocket 监听、Playwright、Mobile、Vue 后台及真实业务任务。
- 加密 SessionProvider、节点与多个真实 OneBot 实例的账号绑定和在线状态同步。

这是所请求模型、Engine 和两个 OneBot 方法的交付，不代表完整平台所有阶段已经完成。

## 官方接口依据

- [Alembic 异步迁移](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic)
- [OneBot 11 公共 API](https://github.com/botuniverse/onebot-11/blob/master/api/public.md)
- [HTTPX 异常类型](https://www.python-httpx.org/exceptions/)
- [HTTPX MockTransport](https://www.python-httpx.org/advanced/transports/)
