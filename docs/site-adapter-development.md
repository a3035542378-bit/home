# Site Adapter 开发规范

## 分层

`Business Task → SiteAdapter → BrowserAdapter → Playwright`。

Task 通过 `context.get_adapter("qq_web")` 获取账号绑定的 Site Adapter，只调用业务只读接口，转换结构化模型为 TaskResult。Task 不创建 Adapter、不操作 BrowserPage、不包含 Selector、不解析 HTML。Site Adapter 负责受控页面、登录状态、页面规则和解析。BrowserAdapter 负责浏览器、Context 生命周期及通用技术操作。

当前 QQWebSiteAdapter 实现 `check_login_status()`、`get_page_status()`、`get_task_center_summary()`、`get_activity_summary()`。增加插件只需继承 BaseTask 并用 `@register_task` 注册，不需要修改 TaskEngine。本阶段没有修改 TaskEngine。

## 生产配置与 Fixture

环境字段为 `QQ_WEB_BASE_URL`、`QQ_TASK_CENTER_URL`、`QQ_ACTIVITY_URL`，默认空，Settings 从 `.env` 读取，Compose 传入应用进程。字段拒绝非 HTTPS、凭据、查询参数、片段和已知内网地址。此校验只是配置语法约束，不能替代 DNS/网络出口控制。

**本阶段没有经过验证的真实 QQ URL 或 Selector，因此生产 RuntimeAdapters 注入的 QQWebSiteAdapter 始终返回 SITE_NOT_CONFIGURED。填写 URL 不会自动启用未经验证的页面规则。** 下一阶段须依据用户提供的真实页面核验规则，再实现真实目标解析及其网络出口策略；不能把 Fixture 规则直接用于真实站点。

`FixtureProfile` 仅由测试或开发验收工具显式构造，限定一个精确的 `127.0.0.1:随机端口` 和固定路径集合。它不能通过 API、TaskConfig 或环境开关开启。`.invalid` 只用于 Fake 返回值，不做网络访问。普通生产 Worker 不导入 Fake 或验收工具。

业务配置只接受：

```json
{"page_key": "TASK_CENTER"}
```

`QQ_WEB_LOGIN_STATUS` / `QQ_WEB_PAGE_STATUS` 允许 `PROFILE`、`TASK_CENTER`、`ACTIVITY_CENTER`，默认 PROFILE。两个摘要插件使用固定页面，不接受额外配置字段，配置为 `{}`。任意 URL、Selector、脚本、Fixture 开关都被 Pydantic 拒绝为 TASK_CONFIG_INVALID。

## 网络和账号边界

受控 Site 会话禁用页面脚本、Service Worker、WebSocket、下载和截图。请求路由只允许固定 Fixture URL 的 GET/HEAD；无匹配请求直接阻断。使用 `route.fetch(max_redirects=0, max_retries=0)`，对所有 3xx 响应阻断，避免路由回调只覆盖重定向首个 URL 的缺口。子资源及 iframe 同样受控。阻断记录为 SITE_NOT_CONFIGURED，不自动重试。响应及时释放；第三方异常原文不记录。

该策略有意只支持静态 Fixture，不宣称已经支持任意真实 Web 页面或解决未来公共域名的 DNS 重绑定。真实域名启用前需明确域名/IP 出口策略、跨域资源和重定向规则，避免仅靠 URL 字符串判断。

相关技术行为参见 [Playwright BrowserContext 路由文档](https://playwright.dev/python/docs/api/class-browsercontext#browser-context-route)；路由不覆盖 Service Worker 请求，因此本实现禁用 Service Worker。

ScopedBrowserAdapter 只允许当前账号创建 Context。Site 会话恢复现有加密 Storage State，退出或取消时关闭 Context；不保存新登录态，不发起登录。缺失/不可读状态、Fixture 页面身份与账号不一致返回 SITE_NOT_AUTHENTICATED / NEED_USER_ACTION。登录态不会写入执行结果。验收工具使用临时目录和临时加密密钥，不覆盖现有账号状态。

## 页面规则与数据

`adapters/sites/qq/selectors.py` 明确标记 **Fixture-only**，集中保存 Selector、允许路径和静态标题字典。真实规则只能在实际核验之后加入。

登录枚举 `QQWebLoginState`：AUTHENTICATED、NOT_AUTHENTICATED、NEED_QR_LOGIN、NEED_CAPTCHA、NEED_DEVICE_VERIFICATION、UNKNOWN。扫码、验证码、短信/设备验证、未知状态均交给本人处理；不点击、不截图、不识别或绕过验证。

任务中心返回 Pydantic TaskCenterSummary：`total`、`completed`、`pending`、有界 `items`；状态为 PENDING/COMPLETED/CLAIMABLE/LOCKED/UNKNOWN。CLAIMABLE 只展示，不领取。活动只返回 activity_count/available_count。

解析同时校验唯一容器、显式空标记、条目上限、字段枚举、键白名单与重复键。缺少容器是 SITE_LAYOUT_CHANGED；结构存在但内容非法是 SITE_PARSE_FAILED；只有显式空列表才能返回 0。每次最多 100 项，超限报错，不返回截断后看似完整的统计。Browser 属性读取有长度和条数边界，不导出 HTML。

Evidence 只含 page_key、final_url（仅 origin）、page_title（已验证静态标题）、parsed_item_count、checked_at。原始页面文本、完整 URL 查询、HTML、个人内容、Cookie、Storage 和 QR 不进入日志或 DB。当前四个插件全部禁用截图；Phase 7 其他诊断任务的受控截图能力保留。

## 错误、重试与测试

仅临时导航、浏览器连接中断/崩溃、启动失败及服务端暂时失败转为可重试 SITE_NAVIGATION_FAILED。401/403 为本人处理，404 为页面变化，其他 4xx 为解析失败。Task 总超时仍返回 TASK_TIMEOUT，不自动重试。站点解析、未配置、登录挑战都不重试。

Worker 沿用独立 RETRY 子记录及现有次数/退避限制，原失败记录不变。四个插件都 scheduled=false，不参与调度。

新增站点需提供：Fake Site 单测、真实 Chromium Fixture 测试、配置与网络阻断测试、账号隔离测试、错误映射和 Worker Retry 测试。真实站点验收状态必须与 Fixture 分开描述。

```sh
backend/.venv/bin/python -m pytest backend/tests -q
PLAYWRIGHT_BROWSERS_PATH="$PWD/artifacts/playwright" backend/.venv/bin/python -m pytest backend/tests -m browser_integration -q
backend/.venv/bin/ruff check backend/app backend/tests backend/alembic scripts
backend/.venv/bin/python scripts/e2e_web.py
```

最后一条要求当前目录为项目根、Docker 开发服务正常运行，且镜像已构建。它会暂停已有 Worker/Scheduler，运行独立 HTTP API、Redis Stream、Worker 和真实 Chromium，通过管理 API 登记四个 TaskDefinition，创建并清理临时账号，最终恢复服务。禁止用于生产环境。
