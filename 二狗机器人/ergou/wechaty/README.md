# 微信群消息监听

二狗的插件装在 Wechaty 宿主中。微信事件由宿主选用的 Puppet 接入组件提供。插件订阅 `message` 事件，经本机 HTTP 提交到二狗，后台的“群消息接收记录”展示处理结果。当前版本接收指定账号、指定群的文本消息；图片、语音、引用解析、成员变动及撤回事件尚未接入。

## 组件核对

| 上游 | 与本次接入的关系 |
| --- | --- |
| [Wechaty](https://github.com/wechaty/wechaty) | 采用它的插件机制、群事件及联系人模型。消息带有群、发送者和来源 ID，选择 Puppet 时仍须验证它是否跨重连保持这些 ID。[Message 接口](https://wechaty.js.org/docs/api/message/) |
| [Wechaty Puppet XP](https://github.com/wechaty/puppet-xp) | Windows 接入项目。其 README 的支持说明列出微信 3.9.2.23，未找到支持本机 4.2.0.13 的声明。 |
| [WeChatFerry 发布记录](https://github.com/lich0821/WeChatFerry/releases) | v39.5.2 标明配套微信 3.9.12.51。该发布物无法作为当前客户端的兼容依据。 |
| [腾讯 OpenClaw 微信插件](https://github.com/Tencent/openclaw-weixin/blob/main/src/channel.ts) | 通道能力声明为 `chatTypes: ["direct"]`，当前发布的能力不覆盖群订阅。 |
| [WeFlow 本地推送协议](https://github.com/hicccc77/WeFlow/blob/main/docs/HTTP-API.md) | 最接近本机只收场景。公开 API 用 SSE 推送群消息，推送示例含群 ID、消息 ID 和发送人显示名。消息详情另有稳定成员字段。文档中的健康检查只返回状态；本机默认端口探测未取得健康响应，当前账号身份和客户端版本兼容性均待验证。 |
| [Agent WeChat](https://github.com/thisnick/agent-wechat) | 独立客户端支持群消息。上游说明复用官方客户端配置适用于受支持的 Linux 版本；新建账号配置需要手机登录。使用独立会话属于另一种部署方式。 |

## Agent WeChat 独立扫码会话

本次经用户授权采用同一微信号的新会话。Windows x64 客户端 2.7.1 已完成手机扫码、账号在线和通讯录同步检查。按完整名称查询“授权测试群”仅匹配一个群。刷新该群成员副本后，本人稳定 ID 的成员状态为 `present`。客户端监听回环端口 6174。二狗使用限此账号、仅有 `read` 权限的本地 API 凭据。上游公开接口的字段以该版本的 OpenAPI 为准。[Windows 发布](https://github.com/thisnick/agent-wechat/releases/tag/v2.7.1) · [本机 API](https://thisnick.github.io/agent-wechat/use/api/)

二狗订阅账号 SSE 事件流，按群 ID、事件类别和来源过滤，再请求匹配记录的消息详情。接收时核对账号、群、发送方向和微信服务端消息 ID。二狗把提交进度写入业务库，重新订阅后按微信服务端消息 ID 去重。一个业务库的同一槽位只允许一个监听进程运行。进程退出后，操作系统释放文件锁，新进程读取最后提交的游标继续接收。

上游返回事件过期错误时，二狗核对账号和群身份，定位仍能读取的最早事件，并从该事件恢复。后台审计中的“事件采集缺口”记录已无法重放的账号游标范围。该范围包含整个账号的活动，无法据此推算目标群漏收了几条消息。当前接入仅处理其他成员发来的新文本。

在二狗项目或解压后的发布目录执行以下命令。此次实机后台端口为 8766，默认演示入口另行使用 8765。将 `python` 换成本机 Python 3.12 的完整路径也可运行。

```powershell
$profileDir = Join-Path $env:LOCALAPPDATA 'Ergou\WechatListener'
$robotDb = Join-Path $env:LOCALAPPDATA 'Ergou\Robot\ergou.sqlite'
python -m ergou.agent_wechat --db $robotDb --private-dir $profileDir status
```

停止服务后，可在各自的终端重新运行监听程序和业务服务。后台首次添加管理账号可运行 `python -m ergou --db $robotDb user admin`，在本机控制台设置口令。

```powershell
python -m ergou.agent_wechat --db $robotDb --private-dir $profileDir listen
python -m ergou --db $robotDb serve --port 8766
```

Agent WeChat 本身需要重启时，运行 `./ergou/agent-wechat-start.ps1 -Wx 路径/wx.exe -DataDir $profileDir`。启动脚本核对官方 v2.7.1 x64 文件哈希，并在独立启动进程内选用当前用户作为新文件的默认所有者。此项处理解决了本机以 Administrator 运行时，SQLite 自动新建的辅助文件被分配给管理员组、上游 API 随后返回 500 的问题。工作区本次下载的程序位于 `build/agent-wechat-v2.7.1/wx.exe`。发布包仅包含二狗接入代码，个人凭据保存在本机私有目录。

新建部署需要先通过上游完成独立扫码，在该用户私有目录提供当前账号的只读令牌文件 `ergou-read-token`，再运行 `python -m ergou.agent_wechat --db $robotDb --private-dir $profileDir link --group-name "目标群名"`。首次绑定从群资料快照的游标开始。重复调用保持现有进度。

## WeFlow 单群接入

适用于已经运行 WeFlow 兼容本地 API 的环境。上游于 11 月 11 日宣布无限期停更。截至本次核查，未找到微信 4.2.0.13 的适配发布记录。本机尚未配置 API，默认端口 5031 拒绝连接。[发布公告](https://github.com/hicccc77/WeFlow/releases/tag/250)

适配器每轮完成后等待三秒，按授权群 ID 拉取增量文本。每页核对群 ID 和数据源账号，每十秒刷新群成员信息。上游 ChatLab 响应的 `meta.ownerId` 取自 WeFlow 的当前配置账号，消息的 `platformMessageId` 取自服务端消息 ID。这个账号信息反映数据源配置，桌面微信是否在线须另行实测。适配器只访问回环地址，使用标准库，无需安装 Node.js。[HTTP 接口文档](https://github.com/hicccc77/WeFlow/blob/main/docs/HTTP-API.md) · [字段生成逻辑](https://github.com/hicccc77/WeFlow/blob/main/electron/services/httpService.ts)

1. 在服务所在电脑运行以下命令核对群。检查程序按完整群名匹配，遇到重名即停止。已知稳定群 ID 时可将 `--group-name` 换成 `--group-id`。如使用其他端口，在子命令前加 `--port 端口号`。

   ```powershell
   python -m ergou.weflow health
   python -m ergou.weflow check --group-name "授权测试群"
   ```

2. 确认输出的数据源账号和群 ID 后，在项目目录登记只收节点，启动二狗。在第二个终端运行监听。各命令提示输入所需凭据。也可在本机启动环境提供 `ERGOU_WEFLOW_TOKEN` 和 `ERGOU_NODE_SECRET`。

   ```powershell
   python -m ergou init
   python -m ergou node "账号ID" "群ID" --listen-only
   python -m ergou serve
   ```

   ```powershell
   python -m ergou.weflow listen --account "账号ID" --group-id "群ID"
   ```

3. 等群成员自然发一条文本，在“群消息接收记录”核对成员、来源消息 ID 及组件 `weflow-chatlab/1`。Ctrl+C 停止监听。每次启动从当前秒开始，重复读取最近十秒以容纳晚到消息，由二狗按消息 ID 去重。监听进程存活期间，断线恢复最多追读最近一分钟；重启期间、长时间断线以及超出重叠窗口的迟到消息可能形成采集缺口。

## 加载 Wechaty 插件

部署需要 Node.js 22.0 或更高版本、可接收群事件的 Wechaty 1.x 宿主，以及由其提供的稳定账号 ID 和目标群 ID。只知道群名“授权测试群”时，要先在接入组件内确认对应群身份。重新连接后核对同一账号、同一群和同一成员的 ID，再启用真实监听。

1. 在二狗项目目录运行以下命令。将占位符换成接入组件提供的 ID，按提示输入本机节点密钥。

   ```powershell
   python -m ergou init
   python -m ergou node "账号ID" "目标群ID" --listen-only
   python -m ergou serve
   ```

2. 在已有的 Wechaty 宿主入口中，于 `bot.start()` 前注册插件。示例假定宿主入口文件在二狗项目根目录，`bot` 是已选定 Puppet 的 Wechaty 实例。节点密钥由宿主的启动环境提供，值须与登记时一致。

   ```js
   import { groupListener } from './ergou/wechaty/listener.mjs'

   bot.use(groupListener({
     account: process.env.ERGOU_WECHAT_ACCOUNT,
     group: process.env.ERGOU_WECHAT_GROUP,
     secret: process.env.ERGOU_NODE_SECRET,
     port: 8765,
   }))
   await bot.start()
   ```

3. 后台选择授权群。账号和群成员关系核验成功后，“运行概览”的账号状态变为 `LISTENING`。等另一位成员发一条普通文本，再到“群消息接收记录”核对来源和状态。正文进入业务处理，列表仅显示元数据。只收节点跳过所有发送任务，包括游戏回复及定时通知。

插件每 10 秒核对登录身份和群成员关系。退出、切换账号或成员关系验证失败会阻止新的投递；桥接服务连续 30 秒未收到心跳会停止接收。每条消息最多尝试投递三次，始终使用同一来源 ID。暂存队列最多 512 条，宿主退出时内存中尚未确认的消息可能丢失。长时间离线的历史补收取决于上游事件源。

## 验证记录

本机使用 Node.js 24.22.1、Wechaty 1.20.2、wechaty-puppet-mock 1.18.2。测试通过 SDK 注册插件，由模拟成员在模拟群发出游戏命令，真实本机 HTTP 服务确认入库，业务工作线程逻辑创建一局游戏，发送队列为空。测试夹具补齐了 PuppetMock 中固定返回空数组的群成员查询。另一组回调测试覆盖私聊、其他群、账号切换、自身消息、非文本、缺失标识、响应丢失和重投。

在装有上述两个 npm 包的宿主目录完成依赖安装后，可从二狗根目录运行：

```powershell
$env:ERGOU_SDK_HOST = (Resolve-Path "宿主目录").Path
python -m unittest tests.test_wechaty -v
```

Wechaty 路线与桌面微信 4.2.0.13 的兼容性仍待验证。上文的 Agent WeChat 独立扫码路线已经通过“授权测试群”的真实来信与两次独立订阅重放验收。
