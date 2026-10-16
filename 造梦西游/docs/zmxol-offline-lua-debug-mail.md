# 桌面 Lua 调试 Mock 邮件

此工具在电脑上的 **Lua 5.4 + Python 3.12 以上**运行，通过本地 ADB 操作已 root 的安卓模拟器。没有确认原游戏存在 Lua 调试 API，不能把这个 Lua 文件放进 APK 当游戏脚本执行。

正式首次赠品保持原邮件 ID 和永久收据；重发采用 **独立递增邮件 ID**，不会删除正式 `committed` 收据或复用旧邮件 ID。电脑助手只追加发信请求，附件由原客户端的 native 工厂生成，再通过原邮箱领取；不直接添加宠物、修改背包、降级角色或改教学完成列表。

| 参数 | 首次正式邮件 ID | 赠品 | 保留的正式收据 |
| --- | --- | --- | --- |
| pet | 900000252 | 独立新增 60 级圣佛邪君，最终形态 | `_offline_mock_pet` |
| pill | 900504100 | 涅槃丹（攻）×1 | `_offline_mock_mail` |
| bagua | 900504200 | 原生生成的八卦乾测试实例 | `_offline_mock_bagua` |

- 正式收据不存在：保持存档内容不变，下次原邮箱列表按原逻辑生成首次赠品。
- 正式收据已领取：分配 `900600000` 起的新 ID，追加 `_offline_debug_mail_<id>`，只含 `version/rid/id/kind/phase=requested`。
- 原邮箱列表：按 kind 生成固定附件并原子保存为 `offered`；宠物使用原角色归属与 native loader，八卦经原工厂分配新的 A5，丹药数量固定 1。
- 原领取：`offered → claiming → committed`，每个独立 ID 仅发奖一次；重复点击、回包重放及重启沿用该 ID 的收据。
- 所有旧调试记录永久保留以防 ID 复用，最多 4096 条；有未完成调试邮件时拒绝新增。每条标题包含 `[Mock]` 与 `[Debug ID]`，不计入自然关卡掉落或自然进化验收。

必须使用含独立 ID 实现的新版离线桥。旧候选桥仅支持三个正式 ID，不能消费新 requested 记录；不要配合旧 helper 删除正式收据。当前模拟器默认 `emulator-5576`，ADB 默认 `/opt/homebrew/bin/adb`。工具不会自动 root，实体手机不在本轮支持范围。

先做无 ADB 操作的检查：

```sh
lua tools/zmxol/debug_mock_mail.lua pet emulator-5576 artifacts/zmxol-offline/analysis-venv/bin/python --dry-run
```

重发前在城镇等待保存完成，避免正在战斗或领取中强退。执行发信请求并启动客户端：

```sh
lua tools/zmxol/debug_mock_mail.lua pet emulator-5576 artifacts/zmxol-offline/analysis-venv/bin/python
```

参数换成 `pill` 或 `bagua` 可发送对应赠品。Python 可独立调用并指定 ADB、序列号和备份目录；对真实备份 dry-run 可预览新 ID，不改变文件：

```sh
python3 tools/zmxol/debug_mock_mail.py --kind pet --serial emulator-5576 --dry-run
python3 tools/zmxol/debug_mock_mail.py --kind pet --dry-run --input /绝对路径/真实存档备份.json
```

实际执行先停止原进程，再读取并备份真实存档，备份权限为 600。原角色 90 级、宠物、背包、教学、正式赠品收据、旧调试收据和未完成关卡奖励均保持原值。临时文件推送到同目录，保留原 UID:GID、设为 600、sync、原子 rename、再次读回比对后启动。若有人同时更改存档，拒绝覆盖。

备份默认在 `artifacts/zmxol-offline/debug-mail/`。执行成功输出备份路径、实际邮件 ID 和新存档 SHA-256，不输出整份存档。正式收据为 `claiming` 或 `offered` 时拒绝重发，应先领取现有赠品。发生错误时客户端可能保持停止，先查看错误与备份，不重复强行重置。

此工具不解除教学遮罩。Python/JS 替身测试与 Lua dry-run 通过不等于安卓完整领取已验证；独立重发的实际 native 奖励与故障恢复证据见下文，最终完整存档断网冷启已通过。

## 最新失败恢复行为（2026-10-14）

当前生产源SHA256 `4d977d982224b10f884802e312e4146b696557272566c0199cfbd41345352719`；完整工具回归 **758 passed / 34.10s**，与validation3历史746及40项邮件助手/诊断结果区分。新候选 `15.7.2-mail-stability-signed.apk` 正在构建，完整新包安装/断网冷启待确认；下方validation3及其验收报告、APK、存档备份均保留，不能把外置诊断实测写成新完整包已通过。

- 根因：领取准备阶段存储失败被捕获后没有送回能结束原UI加载的失败响应，原请求一直等待。现在对有效的受阻请求回非1000失败，经原回调结束加载；不返回成功、不发奖、不消费附件。可恢复范围只包含临时写/fsync失败且尚未rename、读回正式档与baseline完全相同；rename后、存档不能证明一致或发奖后仍fail-closed，不能无条件恢复健康状态。
- 真实验证：独立900600002局部一次fsync EIO后，原UI加载圈消失、附件仍offered，失败前后主save字节完全相同，SHA256 `af28602b9a3cc1be686bf0a99e50c813a969eacd2558378ecc735355cbb44afa`。**同一PID1705、不重启直接点领取**成功，仅新增宠物4403并committed；角色90、既有四宠、背包/点券/角色及旧收据相同。故障注入是测试手段，不称自然设备故障全部情形已验。
- 证据：[失败界面](../artifacts/zmxol-offline/stability-20261014/mail-eio-finished.png)、[直接重试](../artifacts/zmxol-offline/stability-20261014/mail-direct-retry.png)、`stability-20261014/mail-failure.log`、`mail-retry.log`、`save-offered.json`、`save-failed.json`、`save-retry-committed.json`。该增量只修已知失败状态；原生技能/战斗、灵物教学与新包冷启的本轮重验尚未全部完成，不借用旧包结果宣称新包已过。
- [全内容矩阵](zmxol-offline-feature-matrix.md)保留103调查单元/40分组，逐行关联存档契约和UNKNOWN；[下一系统计划](zmxol-offline-next-system-plan.md)首选现有虬龙棍及Lv2法术灼烧石的**常规装备觉醒培养**。常规成本/随机失败契约是第一门禁，不冒用教学免费规则，本轮没有实现新养成系统。QQ数据库/API无变化。

## 2026-10-14 validation3 冻结历史验收

使用 `squad-build/15.7.2-pet-spirit-validation3-signed.apk`（SHA256 `2bfe246229154178080c98efba2341c3d47b18e36d1467ca7c781a1e82143ab5`），桌面助手打包为 `squad-build/mock-mail-lua-debug-v2.zip`。两者位于 `artifacts/zmxol-offline/` 下；旧同ID重置工具不要混用。

原邮箱900000252实际领取为 committed，native生成独立宠物4400/252/Lv60；原火丸4399保留，角色90不变。最终形态模型、五个特殊技能图标和原出战操作均通过；最终签名包断网冷启存档字节一致。随后圣佛邪君实际参与700002天宫道1，原模型/AI/技能与MP消耗正常，原胜利结算保存宠物经验30；翻牌檀木502001数量4→5，收据committed。资源与技能依据客户端；Mock资质不是原服务端随机数值，也不是自然升级到60的证据。

工具746项测试通过；原19项助手测试包含在现24项助手测试中。相关16项诊断契约测试及以下安卓真实验收已分别完成；最终生产脚本完整存档断网冷启已通过。当前真实证据集中在 `acceptance-20261014/pet-claim-verification.json` 及同目录截图/存档/日志。

实际独立重发900600000：领取 `claiming` 落盘后SIGKILL，未新增宠物或扣除附件；冷启同ID补领只生成4401。对同一真实响应原对象重放，生产guard阻止二次发奖，日志 `diagnostic-mail-replay-result` 为pass=true/native_calls=1/replay_blocked=1/diagnostic_guard_blocked=false，存档及奖励数据不变。

再重发900600001：局部单次fsync EIO注入后主存档字节不变、offered仍可领取；恢复生产桥并冷启，原UI重试仅生成4402并committed。正式900000252及前一独立邮件收据永久保留，不复用ID。最终角色90，4400仍出战/经验30，原4399与新增4401/4402均保留。

validation3历史限制：EIO拒绝后持续显示加载圈，需冷启重试；上文新源及同进程直接重试实测已修复可恢复的rename前失败。新完整包冷启仍待确认，rename后/发奖后错误不承诺直接重试。此次为受控故障注入，不代表自然存储故障全部情形已验证。对应证据为 `debug-claim-kill.log`、`debug-replay-result.log`、`debug-eio-failed.log`、`debug-eio-retry.log` 及同目录 `save-debug-*.json`。

最终生产桥断网冷启通过：`save-final-before-cold.json` 与 `save-final-after-cold.json` 逐字节一致，SHA256 `488a0783dd241834073f511eaa7a1e7f00f239e8db86ff7f4b9f59664546c9e2`；实际提取脚本与APK内置桥SHA一致（7a6c…），无诊断脚本，IPv4/IPv6输出仅放行loopback。原ROLE加载保留90级、4400/Lv60/出战/经验30、4399/Lv1/休息/经验32及新增4401/4402/Lv60/休息；正式宠物和两个调试宠物收据、战斗翻牌收据均committed，900038/900040/900041/900044原教学完成记录保留。原邮箱仅余未领取八卦，四宠与圣佛邪君原模型/战字/经验30实际显示。证据 `final-production-cold.png`、`final-production-cold.log`、`final-mail-list.png`、`final-pet-model.png`。

以上仅为本轮宠物邮件及对应关卡验收；全内容改造、其他系统和Android手机未验证。
