# Linux 微信原生音乐卡隔离实验

基线为 agent-wechat v2.7.1。补丁针对微信发送组件，二狗的线上点歌路由继续使用现行版本。实验未使用真实微信账号或群。

## 能验证什么

收到的《任天堂》包含歌名、歌手和 QQ 音乐分享页。原型接受结构化的音乐卡请求，需要额外提供可供手机访问的 HTTPS 音频地址。适配器复用原有账号授权、持久化、幂等键和投递状态处理。收件人身份、原生音乐服务授权、服务端是否接收以及手机能否播放，仅能通过在线验收确认。

实验音频采用 Kevin MacLeod 的 *Outfoxing the Fox*，由 MDN 音频示例提供。已经下载并用 FFmpeg 完整解码，时长约 97 秒。《任天堂》仅用于曲名和歌手字段的本地读回测试。[音频示例与署名](https://mdn.github.io/webaudio-examples/audio-basics/)

## 复现

在 agent-wechat v2.7.1 的独立源码副本根目录执行，PATCH 变量指向本目录补丁的绝对路径。需要 Rust 1.93.1 及上游构建依赖。

```sh
git apply --check "$PATCH"
git apply "$PATCH"
cd packages/native-client-rust
cargo test --locked -p wechat-protocol -p wechat-core --lib native_music
cargo build --locked --bin wx
```

将 ERGOU_PROBE_WX 设为该构建产物的绝对路径，在本目录运行以下命令。脚本使用新建的临时目录、回环端口和未登录账号。服务器验收时还使用了 systemd 的 PrivateNetwork 和 DynamicUser。

```sh
python3 -m pytest -q test_isolated_music.py
```

## 验收边界

- 发送编码测试解码外层二进制请求，核对应用消息子类型为 3，并从内层 XML 读回类型、转义后的歌名和音频 URL。普通分享沿用子类型 5。
- 合成账号测试覆盖音乐意图入队、重复幂等键、不同内容冲突和发送状态不确定时重启不重发。
- 真实 Linux 原型服务中，完整音乐请求抵达账号认证，得到 HTTP 409 和 auth_required。缺音频地址、本地文件地址均在认证前返回 HTTP 400。
- 验证到本地编码与发送入口。尚无微信服务端回执、聊天气泡截图或真机播放结果。

## 2026-11-23 实测

Linux x86_64 隔离进程运行了真实 HTTP 服务。协议库 297 项全过，核心层另跑音乐和普通分享专项 3 项全过。本机 pytest 的 4 个 HTTP 子用例通过。macOS 核心库全跑时 438 项通过、10 项失败、1 项忽略；失败涉及 WXGF 图片预览和账号资料路径，这 10 项单独拿到 Linux 上全部通过。

实验二进制以 musl 交叉构建，仅为适配上游对 glibc 的 renameat2 引用，构建时链接调用同名 Linux 系统调用的薄封装。上述补丁用于上游源码，常规 Linux GNU 构建无需该封装。该二进制未用于生产发布。
