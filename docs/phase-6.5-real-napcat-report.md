# Phase 6.5：真实 NapCat 只读联调

日期：2026-09-11。

**WAITING_FOR_REAL_NAPCAT**

**REAL_NAPCAT_NOT_TESTED**。Phase 6.5 未完成。按后续阶段调整，允许 Phase 7 独立推进，本报告不代表真实 NapCat 已验证。

### NapCat环境

当前 `.env` 的全局 HTTP/WS 地址未配置，数据库 OneBot Node 数量为 0；运行中的 Docker 容器只有项目六个常驻服务。
没有可供本项目连接的真实实例。宿主进程枚举受沙箱限制，不能据此断言宿主一定没有安装 NapCat。
未安装 NapCat、未启动 QQ、未更改用户登录配置，也未发起真实 QQ 操作。

### NapCat版本

NOT_TESTED：未获得真实 get_version_info。

### OneBot版本

本地目标协议为 OneBot 11。远端 protocol_version 未验证。

### HTTP联调

真实 HTTP 全部 NOT_TESTED。独立入口：`python -m app.tools.onebot_diagnose`。
工具读取指定 Node 和绑定 Account，经 OneBotService 解析凭据引用，不通过 TaskEngine 调度，也不修改数据库。
调用 health_check、版本、状态、登录信息，身份通过后才查询好友、群、首个群的信息和本人信息。
诊断继承 OneBotAdapter，固定 READ 白名单拦截 WRITE；没有接收任意 action 的命令行参数。
连接耗时以每个方法的总耗时记录，包含该方法内部预检查、解析和有限重试，不冒充单次网络 RTT。

### WebSocket联调

真实 WS NOT_TESTED。诊断复用 OneBotWebSocketClient 和 EventBus，不使用 LoginStatusHandler，不写入账号状态。
验证连接、合法 heartbeat、事件解析及 heartbeat.self_id 与 HTTP 登录身份一致。
`--observe-reconnect` 在限定窗口内等待操作者停止并恢复 NapCat；恢复后必须再次收到正确身份的心跳才算重连通过。
默认 75 秒，最长 600 秒，可通过参数调整，工具不自动停止外部进程。

### Action兼容矩阵

见 [兼容矩阵](onebot-compatibility.md)。全部真实结果为 NOT_TESTED；未知可选字段的容忍、关键字段严格性和大整数精度已有 Mock 测试。
没有真实不兼容证据，因此没有添加 Compatibility Layer，也没有放宽已有关键字段校验。

### 账号身份验证

真实身份 NOT_TESTED。工具要求指定的 Account 已绑定所选 Node 且平台为 QQ；有多个绑定账号时需显式指定 account-id。
HTTP 身份不匹配立即返回 ONEBOT_IDENTITY_MISMATCH，停止好友/群及 WS 查询。
只显示 QQ 末四位，短 ID 全部遮蔽；不输出昵称、好友内容、群名称或原始事件。

### 断线与重连

真实断线检测、退避和恢复 NOT_TESTED。后续在独立诊断观察期间由操作者正常停止/启动 NapCat；
只有完成“正确心跳 → 断开 → 重连 → 正确心跳”才有恢复证据，单次连接成功不会被记作重连通过。

### 系统隔离验证

本次在没有 NapCat 配置的情况下，原有 202 项测试复验通过，六个常驻 Docker 服务 healthy。
这只能证明未配置时核心系统可用，不能替代真实 NapCat 停启隔离验收。
Phase 6 已验证单独停止 Listener 不影响核心服务，本阶段不把该历史结果当作真实 NapCat 停机证据。

### 性能数据

没有真实数据。诊断输出每个 action 的 elapsed_ms 和好友/群 count；不记录完整列表。
真实典型耗时和列表规模待联调。当前 HTTP 超时、WS heartbeat 超时保持原设置，没有为了联调扩大到不合理值。

### 安全检查

`.gitignore` 包含 `.env`。执行 git status / git diff 后确认当前目录尚未初始化 Git，因此无法审计 Git diff 或提交历史，不能宣称“Git 历史检查通过”。
配置通过 Settings / SecretStr 和 Node.secret_ref 使用，诊断无 token 参数；`--wrong-token` 仅在内存中生成临时随机凭据，不回写真实配置。
日志使用项目现有脱敏与字段白名单，CLI 对未预期异常仅输出固定 DIAGNOSE_ERROR；版本字段也过滤控制字符并遮蔽已知凭据。
源码、测试和文档的当前环境凭据精确匹配扫描结果为 0；敏感关键字用于合法的认证、脱敏与测试代码，不等同于泄露。

### 修改内容

- `backend/app/tools/__init__.py`、`onebot_diagnose.py`：独立只读诊断、身份检查、统计、WS 观察、临时错误凭据模式。
- `backend/tests/test_onebot_diagnose.py`：只读边界、身份隔离、凭据不变性、脱敏、Schema、大整数、WS 清理等 Mock 测试。
- `backend/tests/test_real_onebot.py`：显式启用的真实只读测试。
- `backend/tests/conftest.py`、`backend/pyproject.toml`：注册 marker；只有明确 `-m real_onebot` 才允许真实用例运行。
- `docs/onebot-compatibility.md`、本报告和 README：待验证状态、配置与运行步骤。

没有修改 TaskEngine、Worker、Scheduler、Repository、数据库结构或公共 API。

### 测试结果

基线：202 passed；Ruff 通过；Docker 六个常驻服务 healthy。
新增后：**217 passed, 1 skipped, 2 warnings**，两项 warning 为既有 Starlette 依赖弃用提示。
真实 marker：**1 skipped, 217 deselected**，原因是没有配置 REAL_ONEBOT_NODE_ID / REAL_ONEBOT_ACCOUNT_ID；没有访问 NapCat。
诊断无参数运行实际输出 WAITING_FOR_REAL_NAPCAT / REAL_NAPCAT_NOT_TESTED，退出码为 2。
Ruff：All checks passed。

### 兼容问题

尚无真实响应，不能报告真实兼容或不兼容。远端返回大整数到 JavaScript 的风险已记录在兼容矩阵，未来前端契约应使用 ID 字符串。
`READ_ONLY_CHECKS_PASS` 仅表示一次诊断检查通过，不代表 Phase 6.5 已完成；完整准出还需要真实停启、错误凭据拒绝、Node health 和系统隔离记录。
正确凭据握手成功只标记 ACCEPTED；必须额外运行错误凭据模式，才能证明远端启用了鉴权。

### 最终结论

**WAITING_FOR_REAL_NAPCAT — REAL_NAPCAT_NOT_TESTED。**
诊断工具准备完成，真实准出条件尚未满足。请按下面步骤准备实例后继续。

## 用户下一步操作

1. 按 [NapCat 官方安装说明](https://napneko.github.io/guide/boot/Shell) 的 macOS 或独立 Docker 部署方式安装并启动。
   macOS 方式按官方工具要求备份原文件并完成必要的手动配置。NapCat 独立于本项目 Compose，不与平台捆绑。
2. 本人完成 QQ 登录和必要验证。在 NapCat 配置中启用 OneBot HTTP Server、正向 WebSocket Server 与 heartbeat，并设置访问凭据。
   具体接入选项见 [官方接入说明](https://napneko.github.io/use/integration)。不要把 WebUI 管理端口误当 OneBot HTTP 端口。
3. 在本项目 `.env` 本地填写凭据，不发送到聊天中：
   - 使用多节点映射时，将 `ONEBOT_NODE_TOKENS` 配置为 secret_ref → token 的 JSON 映射。
   - 单节点也必须显式引用：Node 的 `secret_ref=default`，凭据放 `ONEBOT_ACCESS_TOKEN`；全局地址为 `ONEBOT_HTTP_URL` / `ONEBOT_WS_URL`。
4. 在 Swagger 的 Authorize 输入本地管理凭据。用 POST /api/nodes 创建 ONEBOT 节点，填写对应 HTTP/WS 地址和 secret_ref；
   用 POST /api/accounts 创建本人 QQ 账号，account_no 必须与 NapCat 登录 QQ 一致，并绑定 node_id。已有账号通过 PUT 接口绑定。
   记录实际 Node ID 和 Account ID。
5. 地址必须从执行诊断的环境可达：本机 Python 的 127.0.0.1 是宿主，容器的 127.0.0.1 是容器自身。
   Docker 访问 macOS 宿主可用 host.docker.internal；如果还要从宿主执行真实 pytest，建议用宿主与容器均可达的局域网地址或 DNS。
   使用 WS 事件路径 `/event` 或实例实际支持的 `/`，不要使用仅 RPC 的 `/api`。

在项目根目录执行（把 1 换成实际记录 ID）：

```sh
# 环境变量变更后同步到容器，也把新诊断入口加入镜像。
docker compose up -d --build

# 只读诊断，输出脱敏结果；不写入数据库。
docker compose exec -T backend python -m app.tools.onebot_diagnose --node-id 1 --account-id 1

# 临时错误凭据检查，不修改 .env。
docker compose exec -T backend python -m app.tools.onebot_diagnose --node-id 1 --account-id 1 --wrong-token --ws-seconds 15

# 保持运行，在另一个终端正常停止并恢复你自己的 NapCat 实例。
docker compose exec -T backend python -m app.tools.onebot_diagnose --node-id 1 --account-id 1 --observe-reconnect --ws-seconds 180
```

停机期间另一个终端执行 `curl --fail http://localhost:8000/api/system/health` 与 `docker compose ps`，记录核心状态；
恢复后在 Swagger 查询 GET /api/nodes/{id}/health，核对 connection_state、version 和 checked_at（即本项目的 last_health_at）。
不复制完整 login_info 到公开报告。诊断不提供 NapCat 进程管理，不会触发 QQ 写操作。

显式真实测试在节点地址可达的宿主环境运行：

```sh
REAL_ONEBOT_NODE_ID=1 REAL_ONEBOT_ACCOUNT_ID=1 backend/.venv/bin/python -m pytest backend/tests -m real_onebot -q
```

普通测试仍使用 `backend/.venv/bin/python -m pytest backend/tests -q`，即使设置了真实记录 ID，也会跳过真实用例。
如果没有群，get_group_info 将保持 NOT_TESTED 并说明原因，不为测试加群。
