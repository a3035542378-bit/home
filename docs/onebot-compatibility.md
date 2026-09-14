# OneBot / NapCat 兼容矩阵

日期：2026-09-11。状态：**REAL_NAPCAT_NOT_TESTED**。
当前无已配置的 OneBot Node，全局 HTTP/WS 地址为空。没有取得真实 NapCat 版本或响应样本。
以下 Supported 只表示本地实现及 Mock 测试支持，不表示真实 NapCat 验证通过。

| Action | 当前 Adapter | 真实 NapCat | 备注 |
| --- | --- | --- | --- |
| get_status | Supported | NOT_TESTED | online/good 已知字段严格为 bool |
| get_version_info | Supported | NOT_TESTED | app_name/app_version/protocol_version 必填 |
| get_login_info | Supported | NOT_TESTED | 正整数 user_id，先检查在线状态 |
| get_friend_list | Supported | NOT_TESTED | 类型化列表；输出诊断仅记录数量和耗时 |
| get_group_list | Supported | NOT_TESTED | 类型化列表，空数组有效 |
| get_group_info | Supported | NOT_TESTED | 诊断选择列表中的第一个群；无群时标明未测 |
| get_stranger_info | Supported | NOT_TESTED | 诊断仅查询已匹配的本人 QQ ID |

发送、撤回和其他写操作不属于本阶段验证范围。只读诊断使用固定 action 白名单，在 HTTP 请求前拦截所有其他操作。

## Schema 检查

- 当前 Pydantic 模型对已知字段严格校验，默认忽略新增未知字段；没有为猜测中的差异添加兼容层。
- status / retcode 的类型与成功取值均校验，bool 不能作为整数 retcode；data 再按各 action 输出模型验证。
- 缺失关键字段、null 替代必填字段、字符串冒充 bool 会返回 OneBotInvalidResponseError。
- message/wording 自由文本不输出；好友、群、原始事件内容不写入诊断报告。
- 真实响应的字段、null、时间类型和版本差异仍须联调，不将 Mock 响应作为真实样本。

## ID 精度

Python int 和服务端 JSON 编码保留大整数，新增测试覆盖 2**53+1 与 2**63-1。
JavaScript Number 对超过 2**53-1 的整数不能保证精度。现有 Node health 的上游 user_id 仍为 JSON number；
Phase 9 前应为对外 QQ/群 ID 制定字符串序列化契约并补充兼容测试。本阶段不改公共 API。
诊断只输出遮蔽后的 ID 字符串，群 ID 不输出。

## 待实测项目

HTTP 鉴权、真实 WS heartbeat/self_id、断线检测、自动重连、错误 token 拒绝、本人账号匹配、
真实响应耗时、列表规模以及 NapCat 停止期间的系统隔离均为 NOT_TESTED。
每次真实运行需记录具体版本及时间；不能将本矩阵解释为“所有 NapCat 版本兼容”。
