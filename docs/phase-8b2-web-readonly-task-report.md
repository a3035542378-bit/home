# Phase 8B-2：QQ Web 只读业务任务验收报告

日期：2026-09-14。结论：**本阶段 Fixture 范围准出通过；REAL_BROWSER_FIXTURE_PASS；REAL_QQ_WEB_NOT_TESTED。**

## 完成内容

新增 SiteAdapter 抽象、QQWebSiteAdapter、FakeQQSiteAdapter、四个 Task Plugin、账号绑定和加密状态复用、登录状态识别、受控 URL 网络策略、统一解析错误、Worker 重试接入、真实 Chromium Fixture、独立 Docker 验收入口及开发文档。本阶段没有签到、领取、兑换、提交或其他写操作。

开始前基线为 338 passed / 26 skipped；Ruff、Alembic、Docker 六服务均通过，未发现需要先修复的基线故障。

## Site Adapter 架构

`Task → QQWebSiteAdapter → ScopedBrowserAdapter → BrowserAdapter → Playwright`。

RuntimeAdapters 按 TaskContext 注入 Site Adapter，TaskEngine 通过能力声明执行通用检查。Task 只调用四个业务读接口，不创建 Adapter、不访问 BrowserPage、不包含 Selector。没有修改 TaskEngine、Repository 或 API Controller。

生产 Site Adapter 尚无经过核验的真实页面规则，返回 SITE_NOT_CONFIGURED。真实 URL 配置字段已经进入 Settings / `.env.example` / Compose，但填写字段不会自动启用真实页面。Fixture 是测试构造依赖，不能用 TaskConfig 或环境开关启用。

## 新增 Web 业务 Task

| Task | Capability | 超时 |
| --- | --- | --- |
| QQ_WEB_LOGIN_STATUS | site.qq.login_status | 20 秒 |
| QQ_WEB_PAGE_STATUS | site.qq.page_status | 20 秒 |
| QQ_TASK_CENTER_SUMMARY | site.qq.task_center.read | 30 秒 |
| QQ_ACTIVITY_SUMMARY | site.qq.activity.read | 30 秒 |

全部 category=QQ_WEB、task_type=BUSINESS、diagnostic_only=false、read_only=true、idempotent=true、risk_level=SAFE_READONLY、side_effect_level=NONE、scheduled=false、task_version/plugin_version=1.0.0。四个 TaskDefinition 已通过管理 API 登记，executor_type=BROWSER。

## 登录状态模型

QQWebLoginState 包含 AUTHENTICATED、NOT_AUTHENTICATED、NEED_QR_LOGIN、NEED_CAPTCHA、NEED_DEVICE_VERIFICATION、UNKNOWN。除已认证外均停止并返回 NEED_USER_ACTION；HTTP 401/403 同样不重试。缺失或不可读取的状态、Fixture 账号身份不匹配返回 SITE_NOT_AUTHENTICATED。

会话只恢复所属账号的加密 State；不保存或共享 Cookie/LocalStorage。真实 Chromium 验证了缺失状态、其他账号状态不可见、错误身份拒绝、两个账号并发隔离及会话回收。不自动登录、不扫码、不识别验证码。

## Selector 与解析

Selector 集中在 `backend/app/adapters/sites/qq/selectors.py`，明确只适用 Fixture，没有虚构真实 QQ Selector。Pydantic 输出 TaskCenterSummary / ActivitySummary 等模型。

任务容器必须唯一且含显式空标记；没有容器是 SITE_LAYOUT_CHANGED，非法状态、未知任务键、重复键、超限或空标记矛盾是 SITE_PARSE_FAILED。真实空列表才返回 0。任务状态统一为 PENDING/COMPLETED/CLAIMABLE/LOCKED/UNKNOWN；CLAIMABLE 不触发领取。

Fixture 正常任务中心为 total=3、completed=1、pending=1，另 1 项 CLAIMABLE。活动 activity_count=2、available_count=1。

## URL 安全

Task 配置仅接受三个 page_key 枚举；任意 URL、file、localhost、loopback、metadata、内网地址作为参数均拒绝。环境 URL 仅通过公共 HTTPS 语法检查，尚不允许实际生产导航。

活动 Fixture 会话只允许精确 loopback origin 和固定路径，GET/HEAD 方法白名单；脚本、Service Worker、WebSocket、下载禁用。初始请求、iframe、子请求都受控；3xx 不跟随，使用 max_redirects=0，禁止将请求转向 metadata/内网。越界转为 SITE_NOT_CONFIGURED，不自动重试。真实 Chromium 已验证重定向和子资源阻断，Fixture 请求记录没有写请求。

目前没有启用真实域名网络访问，因此不宣称已实现通用公共域名 DNS 重绑定防护。真实规则启用前需另行完成域名、重定向、子资源与网络出口核验。

## 数据最小化

Evidence 限制为 page_key、final_url（仅 origin）、page_title（静态白名单）、parsed_item_count、checked_at。最多 100 项，属性有长度限制；未知标题/任务键不透传。HTML、个人页面内容、Cookie、Storage、token 和 QR 不进入 Execution 或日志。

本阶段四个插件统一禁用截图，包括解析失败和登录页；原 Phase 7 的安全截图能力没有移除。没有启用原始 HTML debug 存档。

## Retry 与 Timeout

只有 SITE_NAVIGATION_FAILED 进入自动重试白名单，并同时满足插件只读、幂等、重试策略和结果 retryable=true。导航超时、浏览器崩溃/断连等转成该错误；401/403、页面变化、解析失败、未配置和本人处理不重试。Task 总超时仍为 TASK_TIMEOUT，不自动重试。

测试确认 Worker 创建新的 RETRY / parent_execution_id 记录，保留原 FAILED 记录；未改变次数/退避/Lease 机制。四个插件不参与 Scheduler。

## Worker 真实链路

Docker 验收使用独立真实 TCP HTTP API、真实 Redis Stream/Outbox、真实 Worker/TaskEngine、真实 Chromium、本地 Fixture 和真实 MySQL。共四个插件均 SUCCESS。验收临时暂停并恢复常驻 Worker/Scheduler，仅处理临时账号的 Outbox；独立 Redis 前缀在退出时清理。

最终执行记录：

| Task | execution_id | 结果 |
| --- | --- | --- |
| QQ_WEB_LOGIN_STATUS | 4fc71d83-e00d-4936-8e6b-51b06e105caf | SUCCESS |
| QQ_WEB_PAGE_STATUS | e5c6febc-1abf-4d29-8e5a-1b56042e1be2 | SUCCESS |
| QQ_TASK_CENTER_SUMMARY | c60ea191-a87d-4abd-b0e4-6773456a2c1c | SUCCESS |
| QQ_ACTIVITY_SUMMARY | 398d2966-1153-4649-a79a-3e8ef314d5dc | SUCCESS |

随后从常驻 API 重新读取这四条执行记录，验证结果及 worker_id 已持久化。临时账号 21 查询返回 404；其任务配置禁用并软删除账号，执行历史保留。初次验收的临时账号 20 同样由工具清理。

## Chromium Fixture 联调

**REAL_BROWSER_FIXTURE_PASS**。

真实 Chromium 回归 43 项通过，包含新增 23 项：登录六种状态、任务中心正常/空/变化/解析失败、活动正常/空/解析失败、缺少状态、账号隔离、身份不匹配、重定向/子请求阻断，以及四个插件 HTTP API→真实 Redis→Worker 的浏览器链路。后者自动化测试使用 SQLite；上述 Docker 独立验收额外覆盖真实 MySQL，二者不混淆。

可复查结果：[phase-8b2-fixture-acceptance.json](phase-8b2-fixture-acceptance.json)。

## 真实 QQ Web 状态

**REAL_QQ_WEB_NOT_TESTED**。

没有用户提供且核验过的真实 QQ 页面、真实 Selector、有效账号 Storage State，因此没有访问真实 QQ 页面。生产执行停在 SITE_NOT_CONFIGURED，未伪造 QQ 业务结果。不影响用户限定的本阶段 Fixture 准出。

## 数据库变化

无表/字段/索引变更，无新增 Alembic Migration。Alembic check：No new upgrade operations detected。

通过现有管理 API 增加四个 TaskDefinition；验收产生 Execution 记录并保留历史。账号和配置沿用已有表及清理语义。未直接用 SQL 登记定义。

## API 变化

无新增路由。沿用任务定义、账号配置、执行提交和执行查询 API。新增四个可执行 task_code 及其元数据；page_key 受 Pydantic 校验。提交返回 202，配置/执行仍遵守 API→Service→Repository。

## 测试结果

| 检查 | 最终结果 |
| --- | --- |
| 普通 pytest 全套 | **406 passed, 49 skipped**，9.42 秒 |
| 独立 Chromium integration | **43 passed, 412 deselected**，31.41 秒 |
| 已执行且通过的不同测试 | **449 项** |
| 总收集 | 455 项；其余 6 项为需真实 OneBot 的未执行测试 |
| 本阶段新增 | 68 项普通 + 23 项 Chromium = **91 项** |
| Ruff | **All checks passed** |
| Alembic check | 无待生成迁移 |
| Compose config --quiet | 成功，退出码 0 |
| Docker Fixture 验收 | 四项全部 SUCCESS |

普通运行跳过的 49 项是 43 项 Chromium（已另行执行）和 6 项真实 OneBot 测试。保留两条已有 Starlette/httpx/AnyIO 弃用提示，没有新增测试失败。

## Docker 验证

最终镜像构建完成，backend、worker、scheduler、onebot-listener、mysql、redis 六个常驻服务均 running / healthy。迁移服务正常退出。未增加新的常驻容器。

## 修改文件

新增：

- `backend/app/adapters/sites/__init__.py`、`base.py`。
- `backend/app/adapters/sites/qq/__init__.py`、`web.py`、`schemas.py`、`selectors.py`、`exceptions.py`、`url_policy.py`、`fake.py`。
- `backend/app/tasks/plugins/qq_web/__init__.py`、`common.py`、`login_status.py`、`page_status.py`、`task_center.py`、`activity.py`。
- `backend/app/tools/qq_web_fixture.py`、`web_acceptance.py`。
- `backend/tests/test_qq_web_tasks.py`、`test_qq_web_integration.py`、`test_qq_web_worker_integration.py`。
- `scripts/e2e_web.py`。
- `docs/site-adapter-development.md`、本报告、`phase-8b2-fixture-acceptance.json`。

修改：

- `backend/app/adapters/browser/manager.py`：受控请求、禁用危险能力、状态恢复标志。
- `backend/app/adapters/browser/page.py`：有界属性读取。
- `backend/app/services/runtime_adapters.py`：账号绑定 Site 注入及浏览器恢复入口。
- `backend/app/services/dispatch.py`：增加只读导航失败重试代码。
- `backend/app/core/config.py`、`.env.example`、`docker-compose.yml`：站点配置字段。
- `backend/app/tools/browser_site.py`：QQ Fixture 路由和请求记录。
- `README.md`：架构、使用约束和真实验证状态。

本目录不是 Git 仓库，以上为本阶段维护的文件清单，不宣称产生 Git commit 或完成 Git 历史扫描。没有修改真实 `.env` 或写入真实凭据。

## 已知问题

真实 QQ 页面未确认；目前仅实现静态 Fixture 规则。真实页面可能需要不同登录识别、DOM 等待、子资源和网络策略，不能未经验证直接开启。环境 URL 字段是待核验的配置入口，当前生产执行保持封闭。

## 尚未完成

真实 QQ Web 只读联调、真实 OneBot/NapCat 验收仍未完成。没有进入 8B-3 写操作、Playwright 业务签到或任务执行器路由器。下一步应先确认真实任务中心页面结构及所需执行能力。
