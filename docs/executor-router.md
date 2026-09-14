# Executor Router 开发规范

## 职责与边界

本阶段只解析能力、选择执行器，不执行 Operation。现有 Task 保持原行为，没有批量迁移或修改 TaskEngine。**Router 当前不是旧执行 API 的全局拦截器**；旧插件能够运行，不代表对应 Operation 已获真实业务验证。

新业务插件优先从 TaskContext 取得账号绑定入口：

```python
router = context.get_service("executor_router")
resolution = await router.resolve(
    operation="QQ_TASK_CENTER_READ",
    context=context,
)
```

返回 CapabilityResolution，selected_executor 为 null 表示不可选择。不要在返回 null 后绕过 Router 直接调用其他 Adapter。当前没有 execute 方法，也没有新增任何写操作。

内部 `ExecutorRouter` 接受 CapabilityService 构建的 RoutingContext。Task 使用 BoundExecutorRouter，不能查询其他账号或通过 TaskConfig 提交自造的运行状态/验证等级。API 通过 CapabilityService→UnitOfWork→Repository 读取账号及节点。

## Operation 与 Executor

OperationCode 登记八项已有读操作、八项保留操作。每项包含 read_only、idempotent、risk_level、side_effect_level、allowed_executors 和所需能力。保留操作没有实现，按未知副作用保守使用 HIGH_SIDE_EFFECT，不宣称支持。

ExecutorType 为 ONEBOT、BROWSER、MOBILE、NONE；NONE 不进入候选列表，未选择用 null 表达。Mobile 只有接口、未配置实现和固定数据 Fake，没有 Appium、uiautomator2 或真实设备连接。

## 验证证据

等级：NOT_VERIFIED、MOCK_ONLY、FIXTURE_VERIFIED、REAL_ENV_VERIFIED。受信任登记表在 `app/executors/catalog.py`，不允许 API 或环境变量提高等级。内部构造注入用于测试，不是外部管理入口。

- Chromium 基础设施：REAL_ENV_VERIFIED。
- 四个 OneBot 读业务：MOCK_ONLY。
- 四个 QQ Web 读业务：FIXTURE_VERIFIED。
- 真实 QQ Web、真实 Mobile、八项保留业务：NOT_VERIFIED。

Browser 基础设施的 REAL_ENV_VERIFIED 不传播到 QQ Web 业务。FakeMobile 健康也不能使业务获得真实验证。后续升级证据应经过真实环境验收和代码登记，不能仅因为节点在线而升级。

## CapabilityResolver

Resolver 综合账号平台/启用状态、执行器白名单、Adapter 能力、节点状态及检查时间、Worker Browser 状态、加密 State 是否可读、各 Operation 站点配置、业务验证证据和 RiskPolicy。

API 不进行主动第三方探测。Node 检查超过 `onebot_poll_interval × 3` 视为过期；身份在线状态不能单凭旧记录放行。Browser Worker 状态来自现有 Redis 心跳；Redis 不可用视为 degraded。API 只读挂载 Worker 的 browser_data 卷以检查加密状态，读出后丢弃内容，绝不返回内容。

State 存在不等于登录有效。没有实时页面登录核验时 authenticated 仍为未知；未来即使加入真实验证证据，也不能仅靠文件存在返回 AVAILABLE。

Candidate 输出：executor、status、runtime_status、verification_level、reason。status 是综合结论，runtime_status 单独保留配置/健康/登录情况。例如 QQ_TASK_CENTER_READ 的 status=NOT_VERIFIED、verification_level=FIXTURE_VERIFIED，同时 runtime_status 可以是 NOT_CONFIGURED。这样不会把“缺少配置”和“缺少真实验证”混为一件事。

人工验证优先阻断；真实 Mobile 未配置明确为 NOT_CONFIGURED。已实现但未真实验证的业务显示 NOT_VERIFIED。AVAILABLE 需要真实业务验证、完整运行就绪和安全只读策略同时满足。

## 选择顺序、风险与 Fallback

筛选顺序是 Operation 白名单、能力、运行状态、验证证据、风险策略，最后按 Operation 的优先级选择。默认顺序在每项 Operation 的登记中独立给出；可通过 `.env` 中 EXECUTOR_PRIORITIES 配置 JSON，例如：

```dotenv
EXECUTOR_PRIORITIES={"QQ_TASK_CENTER_READ":["MOBILE","BROWSER"]}
```

此例只改变顺序，Mobile 仍未配置且未验证，因此不会被选择。未列出的白名单执行器追加到末尾。未知 Operation、越界执行器、重复值和空列表均拒绝。

显式 preferred_executor 只检查指定候选，不默默切换。SAFE_READONLY + read_only + idempotent 才允许自动选择。LOW_SIDE_EFFECT 本阶段不开放；HIGH_SIDE_EFFECT 即使明确指定也不选择，不执行。

`resolve_fallback()` 只是返回下一候选，不运行任务；默认 enabled=false。只有明确开启、安全只读、前次为暂时不可用/降级且下一候选完整 AVAILABLE 时才允许。NEED_USER_ACTION、NOT_AUTHENTICATED、NOT_VERIFIED、HIGH_SIDE_EFFECT 均不能借 fallback 跨执行器绕过。任一候选出现登录挑战或缺失认证，自动选择也停止。

PRODUCTION 和 DIAGNOSTIC 都展示候选；DIAGNOSTIC 不降低验证门槛，不把未验证项标为 AVAILABLE，不赋予执行权限。

## API 与错误

管理鉴权保护：

`GET /api/accounts/{id}/capabilities?mode=PRODUCTION`

mode 可为 DIAGNOSTIC。返回 16 个 Operation，包含 selected_executor、risk_level、status、mode、reason、error_code 和 candidates。不存在/已删除账号返回 404，无效 mode 返回 422，鉴权规则沿用管理 API。

不输出账号号码、Endpoint、Cookie、Token、Storage State、Worker ID 或 Redis Key。reason 为固定状态代码。

统一错误：EXECUTOR_NOT_AVAILABLE、EXECUTOR_NOT_VERIFIED、EXECUTOR_NOT_CONFIGURED、EXECUTOR_NEED_USER_ACTION、OPERATION_UNSUPPORTED。resolve 返回可诊断的结构；内部 require 在无可选项时抛 ExecutorRoutingError。没有为不同 Task 定义不同 Router 错误。

## 当前生产结论

通过新 Router 可选择的真实 QQ Operation：**0 项**。现有 Task 保持兼容，其历史执行行为没有由本阶段统一改写。下一步是实际环境验证，不是继续扩展写任务。
