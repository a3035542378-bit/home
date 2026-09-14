# Phase 8B-1：QQ 只读业务插件验收报告

日期：2026-09-14。结论：**Phase 8B-1 完成**；真实 NapCat 为 **REAL_ONEBOT_BUSINESS_NOT_TESTED**。

## 插件与业务语义

| 插件 | 结果 | Capability | 超时 |
| --- | --- | --- | --- |
| QQ_ACCOUNT_STATUS | 当前账号 ID、脱敏 QQ、最多 128 字符昵称、online/good/connection_state；身份不一致失败 | login_info、status | 10s |
| QQ_FRIEND_SUMMARY | friend_count；可选非空备注/昵称数量 | friend_list | 15s |
| QQ_GROUP_SUMMARY | group_count；角色统计请求明确返回不支持和 null | group_list | 15s |
| QQ_RUNTIME_STATUS | 当前账号、Node 最近记录状态、OneBot 状态、当前执行租约、最近成功/失败摘要 | status | 10s |

能力按既有形式声明：`{"onebot": {"status"}}`，由 Engine 在 execute 前检查。
四项均为 BUSINESS、QQ_ACCOUNT、read_only/idempotent=true、SAFE_READONLY、NONE 副作用、diagnostic_only=false、scheduled=false。
版本 task_version/plugin_version 均为 1.0.0。不参与每日 Scheduler，需通过现有管理 API 显式配置并触发。
本阶段没有写操作、签到、自动浏览、Vue 或风控绕过功能。

## 配置与输出

空配置、好友计数选项、群角色选项、运行历史窗口分别使用 Pydantic Schema，禁止额外字段，严格类型。
execution_history_hours 默认 24，范围 1–168；无效配置在 Adapter 注入之前返回 TASK_CONFIG_INVALID。

TaskResult 显式映射业务字段，不复制 OneBot 原始响应。
Evidence 仅包含 node_id、checked_at 和适用时的 connection_state；没有为填充版本字段增加多余 RPC，也没有伪造协议版本。
任务返回结果，由 Engine/Worker/Service 统一写入已有 result_json；Task 不访问数据库、Redis、httpx 或 Playwright。

## 数据最小化与性能

好友/群列表仅在内存中统计，随后释放局部引用；不保存 ID、昵称列表、群名称或完整明细，不写日志。
群角色统计没有可靠标准字段，因此不执行 N+1 群详情查询。
好友/群列表 RPC 日志只包含固定阶段、duration 和执行关联字段。
零条、普通列表、20,000 条列表均通过测试，直接插件调用每项只有一次列表 RPC；生产 provider 的身份检查为固定开销。
昵称属于用户要求的账号展示字段，最多保留 128 字符，不写日志。

## 账号只读 Context Service

新增 AccountRuntimeReader，由 RuntimeAdapters 绑定 account_id/execution_id 后注入 TaskContext.services。
Task 调用 `context.get_service("account_runtime").snapshot(hours)`，接口不能指定其他账号。
Repository 固定执行四次 SELECT，只选当前账号、Node 状态、当前执行租约及本账号最近成功/失败记录的少量列。
不加载历史 result_json、凭据、全局 Worker 列表或 Redis key。
相同结束时间使用内部记录 ID 排序，解决 MySQL 秒级时间相同时最新状态不确定的问题；排序 ID 不对外返回。

QQ_RUNTIME_STATUS 通过 StatusOnlyAdapter 仅访问 get_status，因此离线/降级也可查询成功，不要求先通过在线登录检查。
该包装器不暴露登录、好友或群接口。其他业务任务保留 Node provider 的登录身份校验。
Node 状态为数据库最近一次健康记录，不主动触发会写库的健康探测。
worker_status 的 LEASE_ACTIVE/LEASE_EXPIRED/UNASSIGNED 仅表达当前执行的 DB 租约状态，不宣称全局 Worker 健康。

## Error Model 与 Retry

复用 TaskConfigError/TaskPreconditionError/AdapterError。业务别名统一：
ONEBOT_NOT_CONNECTED → ONEBOT_OFFLINE，ONEBOT_IDENTITY_MISMATCH → ONEBOT_ACCOUNT_MISMATCH，
ONEBOT_AUTHENTICATION_ERROR → ONEBOT_AUTH_FAILED。超时保留 ONEBOT_TIMEOUT。

四项只读业务把网络重试交给 Worker。ContextVar 按协程隔离所有权，不改变共享连接池的全局可变设置。
作用域内只读 RPC 单次尝试，连接/超时保留 retryable；Engine 再结合 read_only、idempotent、retry_policy 决定资格。
Dispatch 沿用最多 2 次（默认）、5s/15s 退避、新 RETRY execution + parent_execution_id。
认证、身份不符、离线、业务失败、整个 Task 超时不自动重试。
原 Probe/普通 OneBot 使用方式仍在 Adapter 内部短重试并在耗尽后停止；写操作不会因新作用域获得重试资格。
已测试真实 OneBot HTTP 实现配合 MockTransport：委托模式只发一次请求，超时可重试，写请求不可重试，协程之间不串预算。

## 真实队列链路

运行：`backend/.venv/bin/python scripts/e2e_business.py`。
本工具在 backend 容器中通过现有 create_app 工厂启动临时 loopback TCP HTTP 服务，并调用真实 Worker.run。
使用真实 MySQL、Outbox、Redis Stream、锁、租约和结果落库，唯一替身为显式注入的 FakeOneBot。
API 与验收 Worker 位于同一临时验收进程，未替换生产 Worker，也没有增加生产 Fake 开关。

为避免共享 Outbox 的发布竞争，包装脚本暂时停止常驻 Worker/Scheduler，finally 恢复原先运行的服务。
验收使用独立 Stream，发布器只投递自己创建账号的 Outbox，不恢复、重试或消费其他账号。
通过 POST /api/tasks 登记缺少的四个定义；每个 POST execute 返回 202，经 GET execution 确认 SUCCESS。
结束后软删除临时账号、关闭临时 API、清理自身 Redis key，保留任务定义和执行审计。

最终镜像验收记录：

| Task | execution_id | 结果 |
| --- | --- | --- |
| QQ_ACCOUNT_STATUS | bc2d1fc5-d4a7-4e8a-8a66-3b9b7a18713a | SUCCESS |
| QQ_FRIEND_SUMMARY | 93ff8058-7535-45a2-9213-de2b28c37bcb | SUCCESS，friend_count=19 |
| QQ_GROUP_SUMMARY | 6a24fe43-992b-4d29-a291-fa633555c6bb | SUCCESS，group_count=7 |
| QQ_RUNTIME_STATUS | 411b91e7-6c61-4134-abda-fdafdcc81fc8 | SUCCESS，LEASE_ACTIVE，最近成功为群统计 |

19/7 为 Fake fixture 数量，非真实 QQ 数据。验收临时账号没有真实 Node，所以 runtime.node_status=NOT_CONFIGURED；
onebot_status=CONNECTED 来自明确注入的 Fake，不能据此声称 NapCat 已配置。
最终 result_json 已检查不含好友/群 fixture 明细、完整账号号码或敏感状态字段。

## 测试结果

基线：293 passed、22 skipped；Ruff 与六个常驻容器健康通过。

| 检查 | 结果 |
| --- | --- |
| 普通 pytest 全量，包含完整 Engine、Repository/数据库回归 | **338 passed、26 skipped** |
| Chromium integration 回归 | **20 passed** |
| 两组累计通过 | **358 项** |
| Ruff | All checks passed |
| Alembic check | No new upgrade operations detected |
| Compose config | 通过 |
| Docker build / 部署 | 通过 |
| 真实 HTTP + MySQL + Redis + Worker + FakeOneBot | 四项全部 PASS |
| 六个常驻容器 | healthy |
| 系统健康 | api=UP，database=ok，redis=ok，browser=UP |

新增 45 项普通测试、4 项 real_onebot_business 显式用例。26 项默认跳过 = 20 项 Chromium + 6 项真实 OneBot 用例。
真实业务测试只有显式 `-m real_onebot_business` 才允许访问已配置实例；本轮未执行。
两项既有 Starlette/AnyIO 弃用警告保留。实现期间修复了测试断言与 Fake 实参形式、健康状态 fixture 不一致的问题，最终失败数为零。

## 修改文件与数据库/API

- 新增 `backend/app/tasks/plugins/qq/{__init__,common,account_status,friend_summary,group_summary,runtime_status}.py`。
- 新增 `backend/app/services/account_runtime.py`、`backend/app/repositories/account_runtime.py`。
- 更新 `tasks/base.py`、`tasks/engine.py`、`services/runtime_adapters.py`、`services/unit_of_work.py`、`services/onebot.py`。
- 新增 `adapters/onebot/retry_scope.py`，更新 `http_client.py`、`fake.py`。
- 新增 `tools/business_acceptance.py`、`scripts/e2e_business.py`。
- 新增 `tests/test_qq_business.py`、`tests/test_real_onebot_business.py`，更新 conftest 与 pyproject 测试 marker。
- 更新 README、task-plugin-development.md，新增本报告。

无表结构或迁移变化；新增四个 TaskDefinition 数据记录，继续从插件代码提供 metadata。
无新 API 路径，沿用任务定义、配置、POST execute 和 GET execution。没有好友/群明细接口。

## 已知限制与尚未完成

- **REAL_ONEBOT_BUSINESS_NOT_TESTED**：真实 NapCat 仍未联调，不能把 Fake 成功算作 QQ 实测。
- 群角色字段不可靠，不提供角色数量；没有新增详情查询或缓存。
- Node 状态可能滞后于实时 OneBot 状态；Worker 信息是租约摘要。
- 状态专用 Adapter 不验证当前登录身份，只返回绑定 Node 的在线布尔值；身份类与列表类任务仍检查登录身份。
- 历史窗口最多 168 小时，返回最近 SUCCESS/FAILED，不包括 SKIPPED/NEED_USER_ACTION；大规模数据库性能仍待 Phase 10 压测。
- 开发验收工具需要短暂停止常驻 Worker/Scheduler，应通过包装脚本执行，不直接在生产环境运行底层模块。
- Phase 8B-2 浏览类、8B-3 写操作、Vue 和完整部署压测尚未实施。
