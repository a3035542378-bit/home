## 2026-10-15 V5.3 最新增量

原469最小ACK已恢复，但必须在原生状态快照原子提交后绑定请求才能成功；9001/4407出战/休息及断网恢复实测。原合体/自动解除与真灵技能伤害、700002五星和翻牌提交通过。869项实际回归通过、0失败、0跳过，新增18。生产源未改、未新打APK；正式属性/异常/多角色准出边界见[V5.3报告](zmxol-offline-v53-report.md)与v53 verification.json。

## 2026-10-15 V5.2 最新增量

隔离固定兼容实验已通过原融灵458→原工厂→独立真灵背包→材料扣除→存档→断网冷启，9001/4407实际保留；原完整真灵属性窗口已显示。两材料100/100变98/94，原五宠/普通背包不变。正式随机/继承未恢复，生产桥未启用实验；cmd469出战真实失败，合体战斗未准出。最终回归和原档恢复以[V5.2报告](zmxol-offline-v52-report.md)及verification.json为准，历史V5.1“尚无融合实例”不再代表本轮隔离成果。没有构建新APK。

# 造梦西游 OL 离线改造记录

更新时间：2026-10-14（Asia/Shanghai）。

## 2026-10-14 V3 真灵优先与公共质量门禁

本轮按用户V3需求将真灵设为P0主线，装备觉醒为P1调查。[基线](zmxol-offline-v3-baseline.md)、[46ID映射](zmxol-offline-true-spirit-resource-map.md)、[对象选择](zmxol-offline-true-spirit-selection.md)、[觉醒契约](zmxol-offline-awakening-contract.md)及[完整报告](zmxol-offline-v3-report.md)已生成。9045霓云腾蛇为优先补证候选，完整实例/serializer、唯一ID、权威融合规则及事务提交点缺失，实施BLOCKED；没有注入真灵或宣称自然获取/培养/战斗恢复。

原稳定包断网启动实际发生FN SDK SecurityException，历史冷启通过不证明无间歇故障。工作源在离线SDK网络入口沿原IOException失败通路处理，最终源SHA `50bf21c36cf0ac6bce7a30297ec35d9df981c1aeafcfa4d7e012bad6dda8d95c`；本轮完整767通过（新增9），40邮件助手/旧冻结诊断通过（24与全套重复）。两个生产源码冷启进入城镇、save字节一致；这是外置源码测试，不是新签名APK准出。原稳定包2498df…未改写，SDK修复未打入该包。

用户确认手动切换装备/宠物；实例对齐仅4413/4401的A6及4400/4399的tamestate变化，其余物品、宠物成长/技能、90级、余额和收据保留。未覆盖用户新选择；切换后冷启save SHA `f7bfd88676e6c32baebc8158a2fb9f821686fa1482b4a670cdc9599c4329d75f`。当前五宠，火丸4399出战。原备份及全部历史包保留，详见v3-20261014/final-verification.json。下方邮箱/validation3/r11数字属于各自历史版本。

## 2026-10-14 邮箱失败状态修复（本轮增量）

当前生产源SHA256 `4d977d982224b10f884802e312e4146b696557272566c0199cfbd41345352719`；完整工具回归 **758 passed / 31.62s**（最终主线程复跑），与validation3历史746及40项邮件助手/诊断结果区分。新签名包 `15.7.2-mail-stability-signed.apk` 已安装并通过断网冷启，SHA2498df95fd9e3e09019cc96eb2b8ff8e530e7ed258bd203a3a61945a4e7d7246；v1/v2/v3与CRC通过，其余19,144条目内容保持；下方validation3及其验收报告、APK、存档备份均保留，不能把外置诊断实测写成新完整包已通过。

- 根因：领取准备阶段存储失败被捕获后没有送回能结束原UI加载的失败响应，原请求一直等待。现在对有效的受阻请求回非1000失败，经原回调结束加载；不返回成功、不发奖、不消费附件。可恢复范围只包含临时写/fsync失败且尚未rename、读回正式档与baseline完全相同；rename后、存档不能证明一致或发奖后仍fail-closed，不能无条件恢复健康状态。
- 真实验证：独立900600002局部一次fsync EIO后，原UI加载圈消失、附件仍offered，失败前后主save字节完全相同，SHA256 `af28602b9a3cc1be686bf0a99e50c813a969eacd2558378ecc735355cbb44afa`。**同一PID1705、不重启直接点领取**成功，仅新增宠物4403并committed；角色90、既有四宠、背包/点券/角色及旧收据相同。故障注入是测试手段，不称自然设备故障全部情形已验。
- 证据：[失败界面](../artifacts/zmxol-offline/stability-20261014/mail-eio-finished.png)、[直接重试](../artifacts/zmxol-offline/stability-20261014/mail-direct-retry.png)、`stability-20261014/mail-failure.log`、`mail-retry.log`、`save-offered.json`、`save-failed.json`、`save-retry-committed.json`。完整新包断网冷启前后save逐字节相同，SHAec8c83c4364f02d49c7599bf1fe5bd56a677f7fae8dad61fddc748030cca637c；原90级、4400出战/经验30、原火丸及新增调试宠物保留。原模型/技能图标/战字在新包实际显示；本轮未重跑整场战斗或新角色完整灵物教学，原native/资源保持，既有实测证据和自动化回归分别保留。
- 原validation3冻结7a基线的40项助手/诊断复跑40 passed / 0.66s；这些历史诊断绑定旧冻结源，不作为新4d97诊断全量证明。[本轮报告](../artifacts/zmxol-offline/stability-20261014/稳定性与全内容盘点报告.md)。
- [全内容矩阵](zmxol-offline-feature-matrix.md)保留103调查单元/40分组，逐行关联存档契约和UNKNOWN；[下一系统计划](zmxol-offline-next-system-plan.md)首选现有虬龙棍及Lv2法术灼烧石的**常规装备觉醒培养**。常规成本/随机失败契约是第一门禁，不冒用教学免费规则，本轮没有实现新养成系统。QQ数据库/API无变化。

## 2026-10-14 宠物邮件与灵物真实验收（领取、战斗、重放、强退恢复及最终断网冷启通过）

- 本阶段冻结签名基线为 `squad-build/15.7.2-pet-spirit-validation3-signed.apk`，SHA `2bfe246229154178080c98efba2341c3d47b18e36d1467ca7c781a1e82143ab5`，桥 `7a6c9e31c6adc94eae56bafdefb93daffc840303db67ec611624a0c778f8344b`。正式三收据保留、独立调试ID、原252与516模型以及限定虚空缺记录初始化均包含。原资源321文件/15,493,606B/219页；签名、CRC、脚本和原资源逐字节校验通过，工具746测试通过。
- 原邮箱实际领取900000252成功，原native分配252/Lv60/ID4400，收据committed，邮件消失；原火丸4399字节保持，背包/点券不变。完整SAVE一并保存此前关闭的两条经典任务提示900060/900071（原guide表文本已核对），角色其他字段不变且等级90。
- 最终模型与资质技能原UI已显示；Mock配置下界资质经原客户端计算HP3318/MP3268/STR604/DEF134，六born_skill包含普通攻击210000，界面显示五特殊技能图标。不能称这些值是原服务端随机生成的精确数值。原PET出战请求success=1，4400出战、4399休息；validation3完整签名包冷启动ROLE_DATA成功，存档字节完全一致，模型/出战/已完成灵物教学保持。证据见 `pet-claim-verification.json`。
- 补回原516模型后原本命神面板正常。缺失本地虚空表时仅指定原GUI调用点100048、LevelManager单例一致且key sentinel才执行原298a290；已存在空表/零次不重建，构造失败同manager不重试。原教学900040/900041通过真实点击自然保存，并原生发放503148修罗秘令；虚空REQUEST_LEVEL_DATA尚未支持，活动次数/战斗未验收。随后原装备觉醒17步已实际完成：虬龙棍1307/ID4413觉醒并镶嵌法术灼烧石502554/ID4415/Lv2，客户端自然保存900029/900030/900044；不人工设置完成标志。证据 `awaken-after-guide.json`、`awaken-guide-complete.png`。
- 圣佛邪君已实际出战700002天宫道1：原模型、跟随AI与技能正常，战斗中MP消耗、宠物经验0→30；原五星胜利结算自然保存，角色保持90，原火丸经验32不变。随后原翻牌领取502001檀木×1（背包4→5），收据round3/committed。证据 `pet-combat-engaged.png`、`pet-combat-next-wave.png`、`pet-combat-normal-exit.png`、`pet-combat-lottery-reward.log`、`save-after-real-combat-reward.json`。这是重建离线牌池，不能称原服务端概率；本次战斗奖励及宠物经验已在最终生产冷启保持。
- 独立900600000邮件原生领取的 `claiming` 已持久化后实际SIGKILL，进程退出，宠物/背包/点券/正式收据不变；冷启同ID补领只生成4401，收据committed。随后在同一真实manager/response重放原回包，生产guard拦截：`pass=true`、native_attempts/native_calls/replay_blocked均1、diagnostic_guard_blocked=false，save/bag/pet/point不变。证据 `debug-claim-kill.log`、`save-debug-mail-claiming.json`、`debug-replay-result.log`、`save-debug-mail-replay-committed.json`。
- 独立900600001在原领取持久化临时文件fsync处单次局部注入EIO，主存档前后逐字节相同（SHA256 `1b7f6422dde5024c790cd43cd45c1f148f3bc53e8ccd18c73b3b2b93ba343ad8`），附件仍offered、未新增宠物；恢复生产脚本并冷启后原UI重试同ID只生成4402/committed，既有正式与调试收据保持。证据 `debug-eio-failed.log`、`save-debug-eio-before.json`、`save-debug-eio-after.json`、`debug-eio-retry.log`、`save-debug-eio-retry-committed.json`。这是故障注入，不能称自然存储故障实测；失败界面持续spinner，validation3需冷启重试；后续本轮修复和直接重试实测见上文。
- 诊断16项契约测试通过，真实验收已单独记录；诊断脚本不在交付APK内，已恢复生产桥。当前四只宠物：正式4400出战/经验30、原4399保留，新增4401/4402休息；角色保持90。
- 最终生产桥断网冷启通过：`save-final-before-cold.json` 与 `save-final-after-cold.json` 逐字节一致，SHA256 `488a0783dd241834073f511eaa7a1e7f00f239e8db86ff7f4b9f59664546c9e2`；实际提取脚本与APK内置桥SHA一致（7a6c…），无诊断脚本，IPv4/IPv6输出仅放行loopback。原ROLE加载保留90级、4400/Lv60/出战/经验30、4399/Lv1/休息/经验32及新增4401/4402/Lv60/休息；正式宠物和两个调试宠物收据、战斗翻牌收据均committed，900038/900040/900041/900044原教学完成记录保留。原邮箱仅余未领取八卦，四宠与圣佛邪君原模型/战字/经验30实际显示。证据 `final-production-cold.png`、`final-production-cold.log`、`final-mail-list.png`、`final-pet-model.png`。
- 本轮宠物邮件验收通过不等于全内容离线收藏版完成；八卦领取、其他关卡/系统以及Android手机仍未验证。validation3的EIO加载圈限制由上文本轮修复；新完整包复验另记。
- 基线指定 `15.7.2-pet-mail-test-signed.apk` 签名 v1/v2/v3 再验通过，已实际覆盖安装。专用 emulator-5576 只有 com.zmxyol.union.uc 第三方包；备份游戏 files/shared_prefs 共354条，tar 可读且存档字节一致。备份证据位于 `acceptance-20261014/`，存档 SHA `4409aa7db37070d095b48e63c2fb3d4353e67c571f73f7bed5a46606438392a6`，角色90级。
- 用户指定 Lua 命令已真实执行成功，首次宠物收据不存在，存档字节未改变。原邮箱列表成功，900000252 的完整 native 宠物附件已原子保存为 offered；原包缺252骨骼导致 ERROR_ANI_2 自动退出，不能称领取成功。
- 灵物默认509100骨骼在两 APK 中均缺失。原创建失败→init=false/null skeleton→destructor 307a2b0崩溃。仅预览 caller1f829d0回退还不足：详情 caller1f808f8再次请求509100。现限定这两 caller+精确509100.skel回退为同族509135酒仙葫芦（stateoff/stateon），实际加载成功。外观为兼容预览，不是恢复原指天剑资源，不改属性、奖励或教学业务数据。
- 原灵物教学已实际按说明点击完成，遮罩消失。自然 SAVE仅新增completeguide900038；其他存档字段完全相同，等级保持90。证据 `spirit-guide-complete.log`、`save-after-spirit-guide.json`、`after-spirit-guide.png`。validation3最终签名包断网冷启已复验，900038保持。
- 从旧APK补回252原JSON/atlas/PNG，全部原字节不变；原资源318文件/14,891,910B/218纹理页。独立调试邮件从900600000递增，永久保留正式收据和历史ID；替身测试不能替代安卓强退/重放验证。
- 历史候选（已由validation3替代）：`squad-build/15.7.2-pet-spirit-validation-signed.apk`，SHA `a25717ae13a65863584f604e7323329888abcbef77f32f5728bbd24f1800e71a`，桥 `fd99e9f2d883d71ce73de9035005714a381ee4b830077a6fbe8986aa5a140c08`。签名/CRC/内置脚本及318原资源逐字节校验通过。705工具测试通过、1跳过；真实领取/战斗/幂等/冷启动仍在验收。

## 2026-10-12 历史全内容盘点与 r12 续接（当前状态以上文为准）

用户本轮主任务来自粘贴附件，目标扩展为 **15.7.2 全内容离线收藏版**；本轮先盘点及分析，再验收蟠桃园普通战斗、奖励、原打造与装备使用。当前没有将 r12 标记完成或发布。

- [功能恢复矩阵](zmxol-offline-feature-matrix.md)、[历史内容档案](zmxol-offline-historical-content.md)、[真灵调查](zmxol-offline-true-spirit-analysis.md)、[仙器调查](zmxol-offline-immortal-equipment-analysis.md)、[架构检查](zmxol-offline-architecture-review.md)已生成；全量目录及引用证据位于 `artifacts/zmxol-offline/inventory-2026-10-12/`。条目数量不是恢复率，静态调查不代替实机验收。
- 本轮重新执行工具测试 **393 项通过（16.32 秒）**，`node --check` 通过。重新计算 r11 APK SHA256，匹配下文记录；当前源脚本与包内脚本完全一致。未重做 r11 全 ZIP CRC 和签名检查，其下文结果仍属于历史验证。
- 恢复同一 `zmxol_api30` AVD，未清数据。重新禁外网并备份实际存档为 `15.7.2/r12-baseline-save.json`：4434 字节，SHA256 `4fb975c7b4a1a97c66df3facbe0471a654bb5941293a5fccedd7f74c6120a63a`，与 r11 最终存档逐字节一致。实际冷启加载成功，火丸仍出战，见 `r12-baseline-screen.png`。
- 原任务板初次请求失败，候选已按原任务表修复，实际接受“独闯天宫道”并保存 state=2，冷启保持；证据 `r12-mission-candidate-result.png`、`r12-task-route-save.json`。700003 首次真实挑战失败，尚未取得制作书。
- 当前安装仍为 r11 APK，但提取脚本已更换为 r12 诊断候选；不得将此状态称为正式 r12。入口修正后的生产源码 SHA256 为 `f727bba71cc305b3cb82948b411e352357bb210eba760ec0f999a52649d61999`，完整工具测试 567 项通过（20.23 秒）。之前替身测试错误模拟了 MAIL/PET 请求入口，已纠正；新的 Android 验证独立记录。
- 本地 Mock 丹药信已通过原邮件界面领取：504100×1 入实际背包，收据 committed，邮件消失。当前 Lv1 火丸原第一槽为超进化暂选；选药后关闭培养面板自然返还，原 SAVE 仍保存背包1颗及正式空槽，不称正式培养成功。证据 `r12-mock-mail-claimed-save.json`、`r12-pill-close.log`；冷启与八卦后续验收见宠物计划。
- 蟠桃园普通奖励 **502211 是通风灵戒制作书**，原 `forge` 配置输出 type12 装备 **500201**，消耗玄铁20、丝绸10、灵魂1000。现有存档材料足够；r12 必须走真实领奖→原打造→佩戴→自然保存→冷启，不能把书入包当作装备验收。
- 架构检查确认 `drawn` 未领奖收据可被新入场覆盖（生产函数的 Node/native 替身复现，尚非 Android 强退验证）。正在实现限定已支持牌池的恢复与防覆盖；真实重复响应和领奖中断恢复仍未通过。

续接顺序：宠物 Mock 丹药/八卦独立验收，以及蟠桃园普通战斗/奖励 → 原打造/佩戴 → 真实重放与强退 → 正式 r12 包回归。既有 r11、原 APK、旧截图和存档保留；QQ 数据库及 API 没有因本工程改变。ARM64 手机未验收。

## 目标和验收

用户已确认：保留原 Android 游戏客户端，改为可离线游玩的单机版，运行在 Android 手机或安卓模拟器上。两个原始 APK 均保留不变。本工作与当前 QQ 平台独立。

用户另已确认：只有这两个 APK，没有服务端源码或服务端数据。客户端资源可用于核对字段和基础配置，但本地角色、结算及存档逻辑需要另行重建。

第一项验收为：断网启动 → 创建本地角色 → 进入并完成一个关卡 → 保存进度 → 退出重开后继续。通过此验收也不能直接认定全部关卡、养成和其他系统已完成离线改造。

## 已验证的输入

| 项目 | 旧包 | 新包（主分析对象） |
| --- | --- | --- |
| 文件 | `/Users/baize/Downloads/造梦西游OL.apk.1` | `/Users/baize/Downloads/造梦西游OL.apk (1).1` |
| Android Manifest 版本 | 11.6.0 / 1030 | 15.7.2 / 1532 |
| 包名 | `com.zmxyol.union.baidu` | `com.zmxyol.union.uc` |
| 文件大小 | 778,839,157 字节 | 2,087,674,773 字节 |
| 核心游戏库架构 | `armeabi` | `armeabi`、`arm64-v8a` |
| minSdk / targetSdk | 10 / 26 | 10 / 30 |
| DEX 数量 | 1 | 5 |
| 本地 `.sdb` 配置表 | 261 | 513 |
| `.tmx` 地图文件 | 213 | 309 |
| ZIP 全包 CRC 校验 | 通过 | 通过 |

两版主入口均为 `org.yjmobile.zmxy.zmxy`。版本取自 Android Manifest，不能用第三方 SDK 的 `BuildConfig.VERSION_NAME` 代替。

SHA-256：

- 旧包：`ecff6494a962e066812434497282adb614c0163cb7be856c1f64be36861e3d6a`。
- 新包：`1d87033ad10f66f21968ac8cdff0a405063391ab8145152b27bec6861804567f`。

## 静态分析结果与边界

- 核心库为 Cocos2d-x / C++ 原生库，可以定位到关卡、战斗、角色创建、登录、更新、HTTP 请求和保存加载相关类型。类型或函数名称不能单独证明其具体行为。
- Java 主入口加载 `tersafe2` 和 `game`，随后调用 `YJMobileJNIHelper.initHummingbirdSDK()`；助手提供 SDK 初始化、登录状态和更新状态相关方法。
- 新包原生库含官方业务、聊天和世界 Boss 地址。仅检查包内字符串，没有向这些服务发送游戏请求。
- 已核对新版运行时的 JNI 解码入口，确认大部分 `.sdb` 采用 Base64、DES/ECB 和 PKCS 填充，解码结果为 JSON 对象。513 个文件中 512 个通过解码和 JSON 校验；`ai_pet_6000.sdb` 未通过同一格式的校验，原因待查。
- 已读到悟空角色基础属性与 `100001`（九重天）关卡配置。配置表可读并不证明角色创建、进入关卡和结算能够脱离服务器。
- 原生库存在运行期初始化及保护代码。为工具分析创建的 ELF 索引修正、XOR 观察副本仅位于临时目录，不能当作可安装或正确解包的客户端。
- JADX 旧包报告 28 个反编译错误，新包报告 8 个；新版 `org/yjmobile` 目录未发现 `Method not decompiled` 或 `Code decompiled incorrectly` 标记。不能声称已恢复完整源码。

选择新版的依据是 ARM64 支持、更多本地配置和地图，以及较多可读原生类型和资源引用。尚未证明仅替换服务器地址或绕过 SDK 初始化即可离线游玩。

## 运行环境与产物

独立环境和生成产物保存在项目已忽略的 `artifacts/zmxol-offline/` 下：

- `apk-comparison.json`：两版安装包指纹、Manifest 信息、资源统计和验证状态。
- `11.6.0/AndroidManifest.xml`、`15.7.2/AndroidManifest.xml`：解码后的 Manifest。
- `15.7.2/maps-index.json`：309 个地图资源索引。
- `15.7.2/decoded/`：已解码的本地配置及逐文件校验索引，不含外部账号数据。
- `15.7.2/offline-startup.png`、`offline-startup-ui.xml`：原始 APK 断网启动的截图与界面结构。
- `15.7.2/game-runtime-code.bin`、`process-maps.txt`：专用模拟器中读取的核心库运行时代码和映射，用于核对保护层加载后的真实实现。
- `runtime-preflight.json`：启动、CPU 架构及断网规则核对结果。
- `android-sdk/`：独立 Android SDK、AOSP API 30 ARM64 系统镜像、专用 AVD；复用本机已安装的 platform-tools。
- `android-sdk/download-manifest.json` 和 `download-verification.json`：Google 官方下载元数据与校验结果。

临时静态分析目录：`/private/tmp/zmxol-revival-ecff6494`、`/private/tmp/zmxol-revival-newer`。

## r11 发布时运行状态（历史证据）

**r11 已通过火丸捕捉、宠物教学、商城与被动技能教学的保存和冷启动恢复，最新 4434 字节进度重开后完全一致。此前已验证首关、天宫道 1 翻牌及葫芦合成闭环。当前是部分功能测试包，全游戏离线改造尚未完成。** 结果来自专用 AOSP Android 11 / API 30 ARM64 模拟器；原始 APK、QQ 平台数据库和 API 均未修改。

当前安装包为 [`15.7.2-gadget-r11.apk`](../artifacts/zmxol-offline/squad-build/15.7.2-gadget-r11.apk)，大小 **2,083,968,652 字节**。APK SHA-256 为 `b8a6366e003d7541fc1bb29dd62da75af89335d0c1cb96a432797a8803d1d7a6`；内置脚本 SHA-256 为 `aad6de97caa4cbd3a19db48c8b1f795e929d2d34b7f52a3fc072e85927f5a8fc`。安装后的脚本指纹匹配，未替换脚本、无 host Frida 服务或额外注销诊断探针。ZIP CRC、签名 v1/v2/v3 和 315 份恢复资源的原字节校验通过，详见 `squad-build/15.7.2-gadget-r11-build-record.json`。

模拟器启用飞行模式，关闭 Wi-Fi 和移动数据，IPv4 与 IPv6 输出只放行 loopback。APK 移除 INTERNET 权限，只保留 ARM64 库，内置 Gadget 自启动；未使用真实账号。此前已验证无需外置资源或电脑端 Frida server。专用 AVD 以 2 GB 内存运行；模拟器进程曾以 137 退出，原因尚未证实，不能据此认定为游戏崩溃或内存不足，也未排除全部稳定性问题。

### 已通过的实际游戏流程

- 先前已完成悟空建角、九重天原 Boss 五星结算、引导翻牌、回村、打造尾火棍和强化 +1，再保存并冷启动恢复。证据为 `first-clear-result.png`、`first-clear-reward.png`、`first-weapon-enhanced.png` 和 r4 的冷启动记录；r10/r11 使用已有角色继续，未重复全新建角验收。
- r10 已自然完成称号引导、天宫道 1（700002）**75 秒五星**、cmd39 翻牌获得**檀木 502001 × 1**（背包 1→2）、回村和云中子合成**宣花葫芦 500001**。自然 SAVE 后冷启动，4039 字节存档完全一致；完整指纹及证据见 [`r10-runtime-verification.json`](../artifacts/zmxol-offline/15.7.2/r10-runtime-verification.json)。`r10-synthesis-guide.png` 是城镇 NPC 引导，物品以存档为据。
- r11 正式安装保留原有 **3992 字节**存档。蟠桃园（700003）天兵、攻击、掉落火丸显示正常；同一触发操作已不再出现 `ERROR_ANI_2` 资源损坏提示或主动退出。原生葫芦成功捕获**火丸 210**后教学自动回村，完成宠物面板教学和出战操作，随后引导前往赵公明商城；本轮没有完成该关通关或普通翻牌验收。见 `r11-pet-spawn.png`、`r11-pet-deploy-guide.png`。
- 引导结束后，原客户端自然 `REQUEST_SAVE_DATA` 成功写入 **4451 字节**。新增一只火丸（`petid=4399`、`maxglobalpetid=4400`、`tamestate=1`）、`catch_pet=1` 及 900026/900016/900017/900018 引导完成记录；保留 **Lv7、56 EXP、2145 灵魂、尾火棍 +1、宣花葫芦、檀木 × 2**。刚捕获时提取的 `r11-after-catch-save.json` 仍是旧快照，持久化证据以 `r11-after-pet-guide-save.json` 为准。
- 首次宠物冷启动的新 PID 4618 在 17:38:38.669 返回 ROLE_DATA `success=1`。`r11-after-pet-guide-save.json`、`r11-before-cold-start-save.json`、`r11-after-cold-start-save.json` 三份均为 4451 字节且逐字节相同，SHA-256 为 `9ea0e2d7d1146c136b3e7ec5a70f303c450d0e9b8011e994e202105a56458dbc`，宠物及出战状态保留。见 `r11-runtime-log.txt`、`r11-cold-start.png`。
- 商城新手教学由原客户端赠送 **198 虚拟点券**，教学购买一瓶小灵魂药水并在背包使用，增加 **20000 灵魂**。`r11-after-shop-guide-save.json` 为 **4457 字节**，记录 **22145 灵魂、点券 0、900022 引导完成**；此结果只证明教学流程，不代表普通商城全功能恢复。
- 随后的原被动技能教学消耗 **5000 灵魂**，学习**热血 skill 200、grade 1**，生命值 **455→655**。自然 SAVE 的 `r11-after-passive-guide-save.json` 为 **4434 字节**，SHA-256 为 `4fb975c7b4a1a97c66df3facbe0471a654bb5941293a5fccedd7f74c6120a63a`，含 **17145 灵魂、点券 0、900023 引导完成**，火丸仍为 `tamestate=1`。当前抵达讨伐任务引导，尚未点击黄色任务板。

最终复验初次因模拟器进程退出 137 而中断；重启**同一 AVD、未清除数据**并重新禁外网后，正式 r11 的新 PID 1729 在 18:17:22.653 返回 ROLE_DATA `success=1`。`r11-after-passive-guide-save.json`、`r11-final-before-restart-save.json`、`r11-final-after-restart-save.json` 均为 **4434 字节且逐字节相同**，SHA-256 均为 `4fb975c7b4a1a97c66df3facbe0471a654bb5941293a5fccedd7f74c6120a63a`，17145 灵魂、点券 0、生命值 655、热血 1 级和火丸出战状态恢复。`r11-final-runtime-log.txt` 与 `r11-final-cold-start.png` 已重新采集为有效证据，画面停在讨伐任务板教学；首次 4451 字节宠物冷启证据继续保留。

以上文件位于 `artifacts/zmxol-offline/15.7.2/`。当前步骤、截图、存档指纹与验证来源集中记录在 [`r11-runtime-verification.json`](../artifacts/zmxol-offline/15.7.2/r11-runtime-verification.json)。自然操作由主线程实测，存档差异和冷启前后字节一致性另行核验；不以 Mock 测试代替实际游玩结果。`REQUEST_PET_SET_TAMESTATE` 本次仍返回 `success=0`，是客户端本地 `tamestate=1` 随完整 SAVE 持久化，不能称该接口已恢复。

### 已修复的关键阻塞

原 UI 入关要求 `REQUEST_ENTER_LEVEL_MODE_QUERY_ENTER` 返回 `{"code":1000,"state":0}`。新版普通 CCZ 加载路径必须包含 `images/hd`；恢复原 APK 路径后攻击正常，36 份 PVR2 RGBA4444 纹理原字节不变，契约见 `squad-build/texture-path-contract.md`。

保存请求仅允许 `is_saved_from` 为整数 1，并把它作为不持久化的请求元数据。`interaction_data.fight_time` 是非负安全整数的本次战斗时长报告，ACK 后原生清零，不在 ROLE_DATA 中回放，也不据此重复发奖。700002 引导胜利分支省略的角色、背包和关卡保存标志已在唯一核实调用点恢复，同一次原 builder 生成完整快照；未知模块和缺失背包仍严格拒绝。写入使用私有目录临时文件、fsync、rename、目录 fsync，失败不回复成功。

r10 击倒教学天兵后缺失火丸骨骼，实际显示 `ERROR_ANI_2` 并主动注销退出，不能把后续 SDK 生命周期空指针当作起因。r11 补回 210 的原 JSON、atlas、PNG，并接入 `catch_pet` 的严格保存校验；正式包已通过同一操作、捕捉、完整 SAVE 和冷启复验。

### 已确认的资源与实现边界

旧包使用平铺骨骼目录，新版使用分类目录。r11 从旧包恢复玩家 1/5、怪物 300/301/302/303/304/305/322/323/324、火丸 210、悟空 36 组子弹和静态背景 1/2，共 **315 文件、14,221,007 字节**，全部原 bytes 不变。火丸三文件共 14,150 字节，写入 `assets/images/hd/skeleton/pet/`；两组火丸子弹原新包已有，不重复复制。天宫道 700002/700004 的 `staticb=1`，蟠桃园 700003 的 `staticb=2`；新版缺少的两张同路径原 PNG 已补齐。角色 13 的可选内存自测预加载因原 APK 缺失资源而被局部跳过；不能据此认为所有角色和关卡资源齐全。

已验证 native JSON 按模块替换保留未出现模块、完整替换背包以删除旧物品，并保留 uint32 边界与源对象。客户端 Reader 对超大 uint64 本身会转 double，不能声称任意 JSON 整数无损。`savedata.point` 首次创建采用原构造默认值 0，恢复时保留本地既有值。Android ARM64 文件标志已按目标 bionic 头修正为 `O_DIRECTORY=0x4000`、`O_NOFOLLOW=0x8000`。

## 工具与测试

新增独立工具位于 `tools/zmxol/`，不接入 QQ 平台的 TaskEngine、数据库或 API：

- `sdb_codec.py`：配置解码。调用方在内存中提供密钥；源码、参数日志和 Git 中不保存客户端密钥。
- `apk_patch.py`：核对新版原包 SHA-256，替换已定位的启动方法，更新 DEX 校验并校验生成的 ZIP。
- `SignApk.java`：复用本机 JADX 附带的 Android apksig 库签名和验证。
- `PatchAce.java`：复用 JADX 附带的 dexlib2，只保留 ACE 的父类 Context 初始化；属于待运行验证的实验。
- `native_restore.py`：核对输入指纹，恢复运行时代码、导入重定位与初始化表，并固化两处资源读写转发补丁。
- `PatchGadget.java`：在原 Application 静态初始化首部装载固定版本 Gadget，保留原初始化顺序。
- `offline_manifest.py`：只移除 INTERNET 权限节点并修正 AXML 总长度；实际原包移除 2 项、160 字节，其他 bytes 保留。
- `legacy_resources.py`：核对旧包 SHA，恢复玩家 1/5、九重天与天宫道所需怪物、火丸 210 及悟空子弹的真实资源，拒绝缺失、重复或异常路径。
- `offline_bridge.js`：当前 APK 内离线桥接脚本，处理本地登录、已支持关卡奖励与私有存档；适用范围以上述实测为准。

r11 冻结脚本的完整工具测试为 **393 项通过（14.52 秒）**，其中桥接测试 **150 项通过（5.05 秒）**，`node --check` 通过，执行者为 `bridge_tests`。覆盖配置格式、DEX 与签名、原生恢复、Gadget 装载、Manifest 权限移除、原资源核对和桥接数据校验。原子写入失败、重复响应与奖励幂等使用 Mock 契约测试；真实断电、重复网络回包尚未验证。自然游戏保存与强制退出重开证据单独记录。

## 剩余工作

1. 700003 已通过捕宠教学与保存重开，但完整通关、普通翻牌领奖尚待验收；不能从 700002 的成功外推。
2. 700004 的 type 12 成品装备奖励尚未实现。已静态定位原生 factory 的属性和唯一 ID 生成路径，仍需接入并实测。
3. 继续确认讨伐任务、普通商城功能、宠物后续养成、一般出战切换接口、后续装备、其他角色/关卡和非空增量存档模块。当前验证悟空、教学火丸与Mock60级圣佛邪君的模型/出战/700002战斗；其他宠物和自然进化尚未验收，称号列表请求尚未本地化。
4. ARM64 真机兼容尚未验证。测试签名不同于原版，不能覆盖原版安装；不应卸载含有需要保留的原版进度。

## 已选择的普通翻牌规则

用户于 2026-10-10 批准按原关卡物品表重建离线奖励。当前实现范围为 700002（灵魂、玄铁、檀木）和 700003（另含通风灵戒制作书 502211）；每个候选数量 1，从未弃掉的候选中等概率选 1 件，弃牌费用为 0。这些数量、概率和费用是离线版规则，不是原服务器规则。

700002 的真实抽牌、入包、回村和冷启动验收已通过，700003 尚未完成同等验收。700004 中的 1301 等 ID 为成品武器（type 12），不能误当制作书或按普通材料发放；原生属性与唯一 ID factory 已静态定位，但离线奖励接入尚未实现。原首关引导奖励保持原客户端流程，未支持的牌池仍拒绝伪造成功奖品。

## 可复用记录

| 内容 | 类型 | 适用范围 | 来源或验证依据 | 更新时间 | 失效或复查条件 |
| --- | --- | --- | --- | --- | --- |
| 保留原 Android 客户端，离线单机运行 | 本任务约束 | 本次游戏改造 | 用户异步问题答复 | 2026-10-09 | 用户调整目标时 |
| 只有两个 APK，无服务端源码及数据 | 本任务输入约束 | 本次游戏改造 | 用户异步问题答复 | 2026-10-09 | 用户提供新材料时 |
| 以 15.7.2 UC 包作为主分析对象 | 当前状态 | SHA-256 为上述新包的版本 | Manifest、ZIP 资源与 ELF 检查 | 2026-10-09 | 更换 APK 或运行证据推翻选择时 |
| 使用游戏 Manifest 核实版本 | 排查方法 | 含多个第三方 SDK 的 APK | 此包 SDK BuildConfig 的版本与游戏 Manifest 不同 | 2026-10-09 | APK 元数据格式或打包方式变化时 |
| 首个断网阻塞点为 UC SDK 初始化前的联网检查 | 当前状态 | 新版原包、专用 API 30 模拟器 | 截图、界面结构与 FNAdapterUC 实现一致 | 2026-10-09 | 修改初始化流程或更换 APK 后重新实测 |
| 新版 512 个配置表已通过解码与 JSON 校验 | 已验证事实 | 当前新版原包 | `decoded/tables-index.json`，运行时 JNI 解码实现 | 2026-10-09 | 更换原包、解码方式或数据文件时 |
| 跳过 ACE 初始化会让核心库等待加载器信号 | 已验证事实 | 当前新版、ACE 实验包 | `ace-startup-thread-trace.txt` | 2026-10-09 | 更换加载器或原生库实现时 |
| 原生恢复必须同时恢复代码、初始化表和导入重定位 | 已验证排查方法 | 当前新版 ARM64 库 | 递归崩溃指令与 `.rela.plt` 恢复后再次进入更新界面 | 2026-10-09 | 更换 APK、快照或加载器时 |
| 保留关键进展截图；无状态变化时查日志/原因，避免重复截图与盲目点击 | 本任务交互偏好 | 游戏修复验证 | 用户对操作方式的明确反馈 | 2026-10-10 | 用户调整操作偏好时 |
| APK 缺少被内存自测预加载的角色 13 动画；不能假设全部资源齐全 | 已验证事实 | 当前新版原包 | ZIP 全目录查询、崩溃栈、MemoryCheckManager 调用实参 | 2026-10-09 | 提供新资源包或更换 APK 时 |
| 创建面板回调会被轮盘更新覆盖，实际角色以创建请求和存档为准 | 已验证排查方法 | 当前新版角色选择 | 回调即时读到 1，但原生 writer 导出的实际 roleid 为 9 | 2026-10-09 | 改用轮盘真实选中接口后实测 |
| 比对跨版本资源必须检查平铺和分目录布局，不能仅查新版路径 | 已纠正排查方法 | 当前两个 APK | 旧包平铺悟空资源被遗漏；重定位后真实城镇加载成功 | 2026-10-09 | 更换资源格式或版本时 |
| ARM64 文件标志须查目标平台头文件，不沿用宿主或 x86 常量 | 已纠正排查方法 | Android 11 ARM64 存档 | O_DIRECTORY 误值触发 EINVAL；官方 asm-arm64/asm/fcntl.h | 2026-10-09 | 更换目标 ABI 时 |
| 普通 CCZ 纹理的完整加载路径必须含 images/hd | 已验证排查方法 | 15.7.2 ARM64 纹理加载器 | 原生分支、36 项纹理解压验证、APK 路径下攻击动态通过 | 2026-10-10 | 更换引擎或资源加载路径时 |
| 按原关卡物品表重建离线奖励，优先让游戏继续 | 本任务规则取舍 | 缺少原服数量/概率的普通翻牌 | 用户异步问题明确选择 | 2026-10-10 | 用户调整取舍或找到原始服务端规则时 |
| r11 教学火丸 4451 字节冷启、商城/被动教学后 4434 字节最终冷启均通过；当前到讨伐引导 | 续接状态 | 当前新版悟空、API 30 ARM64 | `r11-runtime-verification.json`；同一 AVD 未清数据恢复；出战设置接口本身仍失败 | 2026-10-10 | 桥接、资源、存档格式或 APK 改动后复测；模拟器退出 137 的原因仍待确认 |
| 原位升级提示空间不足时，重启专用模拟器后可用空间从 3.6GB 增至 5.5GB，随后 r9 安装成功 | 已验证排查方法 | 当前 AOSP API30 AVD | adb df、原位安装结果；原角色存档字节保持一致 | 2026-10-10 | 换 AVD 或真实容量不足时重新核查 |
