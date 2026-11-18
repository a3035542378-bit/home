# 业务分层、接口和插件

接入桥校验节点身份及群白名单，调度器保存 Inbox 并按 SQLite 接收序号处理。业务事务提交游戏状态、成员、积分、Outbox 和 Inbox 处理结果。发送器独立领取任务，外部查询独立线程执行。数据库约束、索引及列定义见 [schema.sql](ergou/schema.sql)。本机采用单写者；不同群共享调度线程，性能以实测报告为准。

## Web 接口

管理接口使用登录后的 HttpOnly、SameSite=Strict 会话 cookie。管理服务仅监听 127.0.0.1。所有 POST 接受 JSON。请求体上限 20,000 字节。错误体为 `{"error":"原因"}`。未登录 401、越权 403、参数错误 400、版本或操作键冲突 409、限速 429、存储不可用 503。

|方法、路径|字段与返回|权限与重试|
|---|---|---|
|POST /api/login、/api/logout|name、password 换取八小时会话；退出清除会话|登录按来源限速|
|GET /api/me|登录名、角色、授权群列表|已登录|
|GET /api/my-groups|本人的授权范围内的工作台群名、绑定账号和成员关系状态|已登录|
|GET、POST /api/member-notices|group 指定目标群，写入时另传 kind（join 或 leave）、enabled、该项 version。返回每项申请、确认及生效状态|按群读取，限该群运营或系统管理员写入。真实绑定在本机逐项确认，关闭撤销该项授权|
|GET、POST /api/dialog-controls|读取群开关与管理员名单。保存时提供 group、version、admins 数组|系统管理员或本群运营管理员。群内切换要求真实 @ 和发送者 ID 命中名单|
|GET、POST /api/reply-rules|读取或替换本群有序规则，保存带 version|系统管理员或本群运营管理员|
|GET、POST /api/group-tools|读取本群统计、兑换单、错误记录；写入别名、兑换设置、核销或确认解绑|按群读，限本群运营或系统管理员写|
|POST /api/speech/detect、/api/speech/reply|模拟群上传受限大小的 WAV，或按 seq 合成自己的语音测试回复|须具备目标模拟群写权限|
|GET、POST /api/voice-policy|读取群语音开关、授权、凭据来源和验证状态。提交当前 version，action 为 switch、activate（须附上成功测试的 ticket）或 clear|按群授权。运营或系统管理员可写。实际群语音还须取得本机 confirm-voice 授权|
|POST /api/voice-policy/test|提交 group、version、kind（key 或 token）、secret 和 base64 编码的 PCM WAV 录音。secret 留空可复测当前凭据。返回 transcript、reply、试听用 audio 和 mime，双唤醒及合成成功后返回十分钟有效的 ticket|仅本群运营或系统管理员。测试只向百度提交所选录音和测试回复，不产生群消息|
|GET /api/overview|configured 和 serviceable 分别为授权范围内配置群数及可服务群数|已登录，按群授权范围聚合|
|GET /api/reply-diagnostics?group=…|health 返回当前绑定的心跳、授权和服务状态。records 返回最近十条已登记的点名文字或语音事件的时间、类型、处理状态、发送尝试和回执时间|本群读权限。仅返回状态摘要，不含正文或成员身份|
|GET /api/status?group=…|群、账号、接入模式、状态、绑定版本、配置版本和计数|授权范围内可读|
|GET /api/view、/api/export|group、name；返回表格行或 UTF-8 CSV|读权限；权限和撤回记录限系统管理员|
|POST /api/config|group、version、patch；返回新版本|本群写权限，乐观锁；冲突后取最新版本|
|GET /api/chat-model?group=…|供应商、本群当前模型、版本和最近验证时间。另用模型列表接口读取可选 ID|系统管理员或该群运营管理员|
|POST /api/chat-model|group、version、action。verify 另带 provider、model、key。disable 停用并移除密钥|同上。verify 以固定问候测试所选官方接口，通过后原子替换。相同供应商可留空沿用原密钥。并发冲突返回 409|
|POST /api/chat-model/models|group、provider（deepseek、glm、qwen 或 openai）、key。返回模型 ID 数组 models。百炼按页读取，智谱从公开 OpenAPI 的文字对话模型枚举读取|限本群运营或系统管理员。key 留空可沿用本群同一供应商已验证的密钥。智谱公开目录请求不携带 Key，模型权限由聊天测试验证。读取列表不保存设置|
|POST /api/schedule|group、body、period（一次/每日/每周）、time（北京时间 ISO）、catchup|群写权限；一次请求新建一项，响应不明时先查列表|
|POST /api/operation|group、action、target、key、reason；调分加 points，核对发送加 resolution|群写权限；同键重放返回原结果，包括冲正、停用通知和时效内重试入站|
|POST /api/switch|group、target（账号）、key|系统管理员；校验在线和群归属，未决任务阻止切换|
|POST /api/retention、/api/recall|设置用 group、notice（空串关闭），反查用 group、seq|仅系统管理员，查看有审计，群级 TTL/LRU 内存缓存|
|POST /api/simulate、GET /api/simulation-result|前者 group、key、text；后者 group、seq|模拟群写入、授权群读取；key 去重，真实群禁用|

配置示例：`{"group":"demo-group","version":1,"patch":{"prefix":"二狗","max_games":3,"reward":10,"welcome_window":5,"aliases":{"菜单":"帮助"}}}`。群命令别名属于白名单，保留名冲突会拒绝。积分流水不可就地修改。常见错误码包括 FORBIDDEN、CONFLICT、RATE_LIMITED、CAPABILITY_UNSUPPORTED、ACCOUNT_OFFLINE、STORAGE_UNAVAILABLE 和 DEPENDENCY_TIMEOUT。发送结果 UNKNOWN 可通过管理操作加原因完成人工核对。

## 接入节点 v1

Agent WeChat 可单独运行 `python -m ergou.agent_wechat --db 数据库 --private-dir 私有目录 replies --group-name 已授权群名`。此方式需要本机当前账号槽位的独立 send 凭据文件 `ergou-send-token`。它只认本群已绑定账号收到的、两分钟内以“二狗”开头或确实 @ 账号的文字消息。插件通过稳定幂等键提交回复并核对回执。欢迎、通知和普通群消息均不满足这项定向授权。

只收群消息的节点用 `python -m ergou node 稳定账号ID 稳定群ID --listen-only` 登记。服务端固定该账号的接入模式，心跳状态为 LISTENING，要求 receive、stable_ids 为 true，send 为 false，实际账号匹配且至少一个实际上报的群已授权。此模式仍用 /bridge/event 驱动本地业务；服务端跳过该账号的出站任务，并拒绝 /bridge/claim 和 /bridge/result。30 秒心跳超时后停止入站。完整示例见 [Wechaty 接入](ergou/wechaty/README.md)。

先以本地控制台命令 `python -m ergou node 稳定账号ID 稳定群ID` 登记一项授权，交互输入节点密钥。服务端仅保存其 SHA-256。节点应持有相同密钥，所有请求发往本机端口的 /bridge/，使用 `Authorization: Bearer <节点密钥>`，不复用后台 cookie。节点必须对真实微信账号、实际群成员关系及消息标识负责。仅显示聊天名称的客户端不满足完整模式入站契约。

1. POST /bridge/heartbeat，每 10 秒上报 adapter_version、actual_account、state、groups 和 capabilities。ONLINE 要求 receive、send、stable_ids 均为 true、实际账号相符。客户端登录失效报 NEED_USER_ACTION，传输中断报 RECONNECTING；超过 30 秒无心跳停止领取，5 分钟后需人工处置。
2. POST /bridge/event，上报 group_id、sender_id、source_message_id、event_type、message_type、payload。文本为 `{"text":"二狗 帮助"}`；明确 @ 事件在 payload 给出 mention_account，并将 text 置为去除 @ 的命令。首次成员同步为 baseline / members，确定加入为 join / name，离开为 leave，撤回为 revoke / original_source。返回 ingest_sequence 代表本机已落盘。未收到确认可使用原 source_message_id 重投。
3. POST /bridge/claim，传空对象。返回 task=null 或带 id、biz、grp、binding、body、attempt、expires 的任务。领取时服务端校验身份、群、启用状态、绑定与频率。节点在真正发送前再次核对桌面账号、群、有效期；明确未发才允许报告 RETRY_WAIT。
4. POST /bridge/result，传 task（编号）、attempt、state。ACKNOWLEDGED 表示适配器确认，FAILED 为明确失败，UNKNOWN 为已尝试但结果不明。重复确认返回 updated=false。租约 30 秒后转 UNKNOWN；不会自动重发。机器人账号受限应报告 SUSPENDED。

## 游戏与插件

内置玩法只接收 JSON 可序列化局面和单条动作，业务核心保存局面、规则快照并结算。外部插件采用有向状态图 JSON：id、name、version、core、state_version、prompt、start、goal、states。每个状态映射“动作 → 后继状态”。只执行随核心分发的解释器，插件包不能提交 Python 程序，也不能访问数据库、积分接口或网络。清单最多 32 KiB、100 状态、每状态 32 个动作；单次动作子进程最长 1 秒。

执行 `python -m ergou plugin examples/letter.json` 安装示例“街角信差”。命令 `二狗 开始 街角信差` 开局，按“取信、去西街、签收、交回执”作答。安装会拒绝名称冲突、不可达目标与同版本不同内容。新局采用激活版本，旧局持有原清单快照，重启依照快照继续；重新安装已登记旧清单可回滚。此版本支持声明式状态图插件；可执行第三方 Python 插件及资源沙箱是另外的验收项。

