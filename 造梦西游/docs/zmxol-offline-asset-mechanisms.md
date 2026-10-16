# 离线奖励、资产与事务机制评估

更新时间：2026-10-14。范围：15.7.2 ARM64、单个本地悟空档案。类型：源码与原生契约核查、已保存运行证据复核；本子任务没有操作模拟器或重新执行回归。

结论：**现有邮件、翻牌已经复用原客户端物品工厂、管理器、序列化及同一原子存档入口；本轮不新增统一奖励框架。** 普通商城、服务端合成与高级养成仍缺各自契约，不能用“发一件物品”替代。当前架构支持先恢复一个证据完整的系统，不支持未经核实便放开全内容请求。

## 基线与证据约定

代码引用固定到 [validation3 冻结脚本](../artifacts/zmxol-offline/squad-build/15.7.2-pet-spirit-validation3-frozen.js)，79,742 字节，SHA-256 `7a6c9e31c6adc94eae56bafdefb93daffc840303db67ec611624a0c778f8344b`。冻结脚本行号不随本轮邮箱修复变化；正式实现位于 `tools/zmxol/offline_bridge.js`。原生地址为该版本 `libgame.so` 的库内 VMA，须加运行基址，不可跨版本复用。

运行事实引用 [2026-10-14 验收报告](../artifacts/zmxol-offline/acceptance-20261014/验收报告.md)、[r10 运行记录](../artifacts/zmxol-offline/15.7.2/r10-runtime-verification.json)及 [r11 运行记录](../artifacts/zmxol-offline/15.7.2/r11-runtime-verification.json)。历史记录不是本轮重新测试；746 项工具回归、40 项邮件相关回归的执行结果由主任务核对。

## 五条资产链路

| 链路 | 请求与真实资产变化 | 入库、消耗及持久化 | 幂等与验收边界 |
| --- | --- | --- | --- |
| 邮件 | cmd552 `REQUEST_REQUEST_MAIL_LIST_NEW` 展示收据；cmd14 `REQUEST_MAIL_RECIEVE_REWARD` 先保存原请求快照与 `claiming`，再由原 MailMgr handler `0x2afba4c` 发附件。 | 冻结脚本 L371 `prepareMockMailClaim`；L860 拦原 ACK `0x2fe924c`，在原清理前序列化 bag、point，宠物还序列化 pet；L386 `commitMockMailReward` 同次写资产与 `committed`。失败不能当领取成功。 | 正式三类及每封独立调试信都有永久 receipt；L891 handler 对 delivery.used/committed 校验。同一信只领一次，重发须新 ID。真实宠物、强退恢复及响应重放通过；此前 EIO 需重启，邮箱失败恢复为本轮待修范围。 |
| 战斗结算 | cmd38 `REQUEST_LEAVE_LEVEL`、cmd548 `REQUEST_LEVEL_LEAVE_NEW` 捕获原 `savedata`；经验、掉落、宠物战斗经验已由原客户端应用。 | L440 `captureOrdinaryLeave`、L618 起保存请求；模块完整值替换，不能将交互收入报告再次发放。实际700002 petexp 0→30、角色90保留。 | 通关保存与翻牌分开；700002/700003有自定离线牌池，其他关只保留已支持通关快照，不假造抽牌奖励。 |
| 普通翻牌 | cmd39 `REQUEST_LEVEL_LOTTERY`；L454 `prepareLottery` 固定一个 drawn.reward 后回原 LevelMgr `0x29b9468`。 | 原 parser `0x29993ec`、工厂 `0x3c6b750`、入包 `0x2d41900`；原处理包含弃牌扣费。L786 暂缓原 HANDLED/GO_ON，L462 同次提交 bag、point 与 committed 后才放行。 | `entered → offered → drawn → committed`，round区分重新挑战与旧回包；冷启恢复只发同一已保存 reward。实际700002 檀木×1通过；数量1、等概率、弃牌费0是获授权的离线重建，并非原服规则。 |
| 商城 | 当前白名单没有通用购买请求或商品响应恢复。r11原新手教学赠198点、买小灵魂药水、使用增20000灵魂。 | 教学原动作生成实例/扣款，再经完整 SAVE 保留 bag 与 point；不是桥接另建的商城发奖实现。 | 教学保存和冷启通过，不能外推普通商品、库存、限购、点券购买或交易行。无对应通用商店 receipt。 |
| 合成/打造 | 已验原教学宣花葫芦合成和尾火棍打造/强化；不代表全部配方离线。 | 原客户端本地配方动作生成结果、扣材料/灵魂，再走 SAVE。bridge没有通用扣材函数或服务端合成 handler。 | `compose_by_server`/`forge_by_server` 按条目决定，字段存在或值0仍不足以证明该具体操作已验。服务端配方需原生响应/实例/消耗/保存契约。 |

商城与合成没有可直接合并的重复 JS 奖励实现；把教学写成完整商城/完整合成会夸大恢复范围。邮件与翻牌 UI、响应对象、通知数量不同，也不能仅因都叫 reward 而合并回调。

## 已有可复用部分

| 能力 | 已有共享入口与依据 | 必须保留的差异 |
| --- | --- | --- |
| 实例生成 | L744 原 `itemFactory=0x3c6b750`；翻牌恢复L754起调用，八卦预览L812、宠物预览L829也调用。原生 RTTI、serializer 指纹均核验。 | 堆叠材料只需A2/A4；装备/八卦需要原完整实例/A5；宠物包装对象须解包、检最终stage=5、取原宠物serializer。不能把A5与petid混为一类ID。 |
| 背包入库 | L747 原 `addItem=0x2d41900`；翻牌恢复显式调用，正常翻牌与邮件由各自原 handler执行入库。 | pet奖励实际进入 PetMgr.petinfo，非 bag.item；必须完整验证新增一个petid、旧宠物不变、容量与全局计数。 |
| 序列化 | L710 `withBagSnapshot`、L720 `withPetSnapshot`共用原x8 ABI thunk；bag serializer `0x2d4053c`、pet serializer `0x2c1ab40`。 | 总 builder `0x2fe1b50`会消耗增量/更新缓存，不能反复调用补快照。宠物snapshot不等于普通物品snapshot。 |
| 货币 | L726 `currentPoint`读取 Player虚表+0x58的int64，L386/L462通过原Json writer写盘。bag内灵魂spiritcount是另一余额。 | point不在bag内；不能只存背包、写任意0或经过JS Number丢64位精度。灵魂收入报告不等于当前余额，消费后余额可低于报告累计收入。 |
| 原子存档 | L471 `capture`构造完整候选；L174 `commit`短写/EINTR处理、临时文件fsync、close、rename、目录fsync；成功后更新内存baseline。 | “文件原子提交”不等于任意原生内存操作可回滚，也不等于任意并发请求有隔离。当前仅支持已核实单档及原回调时序。 |
| 奖励幂等 | lottery receipt和各mail receipt都在同一文件，资产与最终receipt一次capture；成功后才释放原ACK/通知。 | mail ID不可复用；lottery round必须允许新挑战；post-grant失败和pre-grant失败不能同样处理。 |
| 材料扣除 | 已验合成、教学购买使用原客户端扣除；正常翻牌原回调可扣point。 | 尚无证据证明高级服务端合成可以调用同一个扣材入口。须按响应的consume/remove_goods及管理器/序列化核实；不新写泛化JS扣材器。 |

八卦的唯一实例 ID 在 **offered准备阶段** 就由原工厂保留，且 `maxglobalitemid + reward实例`一起落盘（L300）；宠物模板的预览petid=1不入包，在 **实际领取阶段** 原生分配唯一petid（L35/L321/L346）。两者阶段不同，通用“领取时统一分配ID”会破坏现有安全约束。

原生与事务细节见 [普通翻牌契约](../artifacts/zmxol-offline/squad-build/ordinary-level-lottery-contract.md)、[奖励恢复契约](../artifacts/zmxol-offline/squad-build/native-reward-recovery-contract.md)、[新增模块契约](../artifacts/zmxol-offline/squad-build/native-save-extra-modules-contract.md)。

## 配方核查与范围修正

直接读取15.7.2 `decoded/database`：

- `compose`共167条，`compose_by_server=0`有43条、=1有124条；`forge`共156条，`forge_by_server=0`有108条、=1有48条。这是配置分类，不是恢复数量。
- **宣花葫芦配方是compose[502301] → 500001**，spirit_cost=2000，本地标志0；材料为500200/3301/4501。compose[502300]实际是枯叶灵→500000，不应串作葫芦配方证据。
- forge[502211]是通风灵戒制作书，本地标志0，输出装备500201，玄铁20/丝绸10/灵魂1000；type13书入包不等于type12装备已打造。
- 原教学合成2000灵魂已扣且存档恢复是运行证据；没有核实所有材料字段、后续成长或服务端配方时，不声称全部闭环。

## 高级养成的架构限制与最小改动

目前是严格白名单的原客户端桥接，而非已完整重建的服务端。对已核实本地系统，可继续沿现有原loader/serializer/manager恢复，无需引入新数据库或通用资产框架。

| 限制 | 直接证据 | 最小处理 |
| --- | --- | --- |
| 新savedata模块会被拒 | 冻结脚本L80只允许roledata/bag/level/point/pet/mire及有限报告字段；L84拒非空eggdata/novice进度，L85 mire只允许storytask。 | 先追具体系统原serializer、loader、dirty位与ROLE_DATA投影；证明快照/增量语义后仅加该模块校验和保存。未知模块继续拒绝。 |
| 新养成交互会阻塞保存 | L89 interaction只接受get_base_item_list/fight_time/catch_pet；原计数还包括get_degree_exp/up_degree_level等，但当前未支持。 | 先确认该报告是否已应用的收入/进度、ACK会清什么、登录是否依赖；不能因为名称像日志就全部丢弃。 |
| 同进程失败不能全局清failed | L497 capture异常标failed；rename成功但目录fsync失败可能磁盘新、内存旧，见native-save-review。 | 邮箱本轮只在证据足够时恢复：未rename、未原生发奖且主文件/基线一致，才能重新接受请求。原生已经发奖或rename后不确定，必须回滚/重载已确定快照，不能直接清latch重发。 |
| 服务端养成可能返回完整新实例和多资产消费 | 当前邮件限定三种附件；商店/合成无通用协议恢复，物品形状已区分材料/八卦/pet。 | 只恢复一个确定配方或培养操作；奖励实例、消耗、货币、培养进度和receipt同次提交，并验证失败/重复/强退。原精确数值未知就标未知。 |
| 响应、业务完成和UI完成不能混用 | 翻牌需要HANDLED+GO_ON；邮件需要原ACK/clear及GO_ON；原请求未准备时wire会阻断成功响应。 | 失败走真实错误/取消加载分支，附件可重试；不借成功通知把失败状态假装完成。 |

不建议本轮抽象 `RewardService`、通用item JSON构造器、统一ID分配器或递归合并存档。它们会把类型差异、客户端报告/快照差异和请求原时序隐藏起来，当前没有第三条已完整核实的重复奖励链证明收益。

下一系统实施时，优先复用现有capture、原工厂/manager和snapshot helper；只有新增系统确实出现第三处相同的“bag/point/pet+receipt提交”代码、同一失败语义也被验证，才考虑提取一个小型提交helper，不合并系统状态机。

## 测试准出与未验证项

资产闭环应对每个具体操作验证：原入口→真实实例/属性→消耗正确→使用/战斗→自然保存→断网冷启。新增操作至少覆盖成功、容量/材料不足、pre-grant写失败、post-grant提交失败、rename后目录失败、重复真实响应、领取中强退、旧资产保留。成功ACK必须晚于实际持久化；错误结束加载不代表发奖成功。

既有测试证据定位：`test_offline_mock_pet_mail.py::test_original_mail_grant_appends_one_pet_and_commits_before_ack_and_go_on`、`test_pet_and_bag_commit_is_atomic_on_snapshot_and_storage_failure`、`test_directory_sync_failure_after_rename_does_not_duplicate_pet_on_restart`；`test_offline_bridge.py::test_lottery_wire_calls_native_reward_once_and_commits_before_success_notifications`、`test_recovery_restart_uses_actual_durable_receipt_after_commit_error`；`test_offline_mock_mail.py::test_mail_point_response_preserves_native_int64_text`。这些执行生产JS、原生/IO替身仍属自动化契约测试，不代替模拟器或真实断电测试。

本子任务只新增本文并核对引用与配置统计，未改源码、数据库、API或既有存档；不重复跑全量回归。邮箱本轮真实修复结果、下一养成系统选择与新APK由主任务另行交付。物理断电、实体手机、全部商城/合成及全内容仍未验证。
