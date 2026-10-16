# 15.7.2 真灵子系统调查

## 2026-10-14 V3 增量核查（当前结论）

**真灵业务闭环仍未完成，实施选择BLOCKED；优先继续补证9045霓云腾蛇。** 本轮重新读取180条pet配置、704条融合配置及46个真灵的全部born_skill/AI关联，对两原APK和指定mail-stability包重算指纹，并逐atlas核纹理分页。详见[资源映射](zmxol-offline-true-spirit-resource-map.md)与[选择评分](zmxol-offline-true-spirit-selection.md)，下文10/12调查保持为历史证据，不代替本轮运行验收。

- 原15.7.2及当前包均有9043/9044/9045基础组；9043/9044各四页、9045一页，atlas引用页全部存在。旧11.6.0另有16组平铺基础模型，尚未验证旧动画与新native兼容。两包候选总19组，另27组在已证布局未找到；这仍不是完整战斗资源闭包。
- 46个真灵born_skill均存在于pet_skill，ai_file均有已解码表。逐ID配置、技能原记录、融合target与材料、模型成员SHA/长度已生成可复现JSON。图标、音效、技能子弹/特效、合体技能逐ID动态引用与图鉴运行仍UNKNOWN，不从文件名猜归属。
- 本轮重新反汇编0x2bfca74真灵loader、0x3aad6d4真灵工厂、457开包sender、458融合sender/consumer和459升级sender，证据在v3-20261014目录。指令确实使用独立PetMgr+0x298并调用原工厂；llvm-objdump附近符号名不能当业务函数名。完整serializer、ID分配、权威结果计算及dirty/提交点尚未闭合。
- 9045被38条beast_mix_rule列为候选；本包资源存在且无需迁移旧骨骼。9043/9044没有本次融合target记录，原规则文本71000276另描述圣/魔青龙方向进化活动、材料、返还及随机天赋，依赖更复杂。未证明9045某条配方与圣/魔进化完全独立时，也不把候选优先级说成可实施契约。
- 当前存档没有true_spirit_bag；桥接根白名单明确拒绝此模块，原真灵协议未适配。模拟器当前90级五只普通宠物不是任何真灵实例。城镇菜单与普通宠物面板只读检查未进入真灵系统；总入口解锁条件与不可进入的精确原因未确认，不将“没有入口”直接归因服务器标记。

获取、培养、合体、实战、结算及真灵断网冷启均未执行。由于完整实例/融合/保存硬门禁缺失，本轮未返回真灵空成功、未注入真灵对象、未扣任何材料，不构建或交付“真灵已恢复”APK。现有capture/原工厂/原子提交可复用，但文件原子写不等于native内存交易可回滚。

新增只读映射工具及隔离ZIP pytest验证了分页缺失、危险引用、旧包布局、ID与权重区分及缺技能标记；它们是调查工具测试，不能算获取/培养/战斗异常验收。关于原稳定包新发现的SDK冷启异常与修复候选，另见[V3报告](zmxol-offline-v3-report.md)。

更新时间：2026-10-12。范围：用户提供的两个 APK、15.7.2 ARM64 原生库、已解码配置、r11 文件与现有离线桥接。本文为只读静态调查；没有操作模拟器、修改桥接或验证真灵实机流程。

**结论：15.7.2 确有完整的真灵客户端分支，包括融合、培养、装备、合体技能、血脉、捕捉/点化及特殊进阶；r11 的普通宠物捕捉成功不能计作真灵恢复。** 真灵使用独立的 `savedata.true_spirit_bag`，主要成长操作由专门请求返回结果，当前桥接没有实现这些协议。配置中的部分概率与消耗可复用，但服务端完整结果生成规则及部分资源仍为 UNKNOWN。

## 证据范围与标记

- **STATIC**：本次读取配置或反汇编确认；证明客户端存在该行为，不证明离线已运行。
- **HISTORY**：历史项目记录；没有在本次重新执行。
- **UNKNOWN**：缺少调用链、实际请求或运行证据，不能当作默认值或成功条件。
- 源配置目录：[decoded/database](../artifacts/zmxol-offline/15.7.2/decoded/database)。原生分析文件为 `/private/tmp/zmxol-revival-newer/lib/arm64-v8a/runtime-analysis-libgame.so`，地址均为该 15.7.2 ARM64 库相对偏移，禁止跨版本套用。
- [r11 APK](../artifacts/zmxol-offline/squad-build/15.7.2-gadget-r11.apk)、[历史冷启截图](../artifacts/zmxol-offline/15.7.2/r11-final-cold-start.png)、[主记录](zmxol-offline-revival.md)已确认存在。它们不是本次真灵验收证据。

## 系统身份、入口与解锁

| 项目 | 已确认依据 | 边界 |
|---|---|---|
| 真灵基础对象 | `pet.json` 共 180 行，9000–9045 共 46 行 `is_beast=1`，type 17；`0x2e103dc..0x2e103f8` 读取 `is_beast` 并写 PetConfig `+0x5c0` 的保护布尔值 | 宠物与真灵共用基础类型，不能共用背包保存契约 |
| 培养入口 | 原生 `YJBeastDevelopLayer` RTTI `0x51ed570`，另有 `YJBeastUpgradeLayer`、`YJBeastQualityLayer`、技能预览和图鉴 | 总入口首次开放的角色等级、任务标记及全部运行门槛 UNKNOWN |
| 融灵主宠资格 | `rule.json[71000019/71000021]`：指定超进化宠物达到 75 级；列举青龙妖圣、白虎战神、烈焰金刚等 | 这是包内规则文本，未冒充所有原生校验已逐条验证 |
| 融灵辅宠资格 | `rule.json[71000020/71000021]`：指定宠物达到 60 级，或符合品质组合的真灵 | A/B/A+/S 等组合另有 71000022–71000024；完整组合以配置为准 |
| 原生教学 | `guide_step.json[900552/900553]` 显示控制真灵技能自动释放的教学 | 教学条件与实际按钮可用性未运行验证 |

`primordial_spirit*` 的“元灵”（例如 type257 的8267000元灵蛋）、`fairy_equip_spirit*` 的“器灵”以及仙器的元神投影是其他系统，不因名称含 spirit 归入真灵。

## 配置、成长与材料

| 配置表 | 行数 / type | 可复用内容 |
|---|---:|---|
| `pet.json` 真灵子集 | 46 / 17 | 品质、基础属性、资质、成长因子、技能、AI、血脉、出战状态、资源 ID |
| `beast_mix_rule.json` | 704 / 84 | 指定主辅宠组合、材料、目标候选权重、天赋及血脉候选 |
| `true_spirit_main_config.json` | 11 / 143 | 品质组合、相同/不同条件的结果权重、天赋数与候选权重 |
| `true_spirit_auxiliary_config.json` | 66 / 144 | 原宠物与升级/跨级结果、天赋 ID 关联 |
| `true_spirit_blood_config.json` | 52 / 102 | 血脉来源、主辅品质、目标及组合概率数组 |
| `beast_armor_skill_desc.json` | 188 / 83 | 合体技能时长、消耗、伤害/减 CD/持续时间系数、升级及额外升级消耗 |
| `pet_lineage.json` | 6 行 | 凤凰、青鸾、玄武、邪龙、玲珑等血脉定义 |

具体可核验样例：

- `beast_mix_rule[6820022]`：主辅均 221；`other_materials=[503345,2,503346,6]`；`target=[221,5000,9027,3000,9029,2000]`。本地存在候选及权重，**不等于已证明最终服务端如何叠加幸运、定向材料、血脉和保底**。
- `true_spirit_main_config[7522000]`：`out_different=[1,5000,4,3000,6,2000]`、`out_same=[1,5000,3,3000,5,2000]`，并有天赋权重。数组含义须与原调用核对，不能直接当作已验收的 RNG。
- `true_spirit_auxiliary_config[7530212]`：火猿 212 → `upgrade_id=9003`、`double_upgrade_id=9006`、`talent_id=[209903]`。
- `true_spirit_blood_config[6950001]`：`blood_source=6940001`，主品质 2、辅品质 1，`target=[9012]`、`probability_of_composition=[10000]`。
- `beast_armor_skill_desc[9500010]`：`mp_required_base=100`，伤害提升数组 `[0,1,2,3,4,5]`，`upgrade_cost_id=503347`、数量 `[0,5,15,30,50,75]`，`max_grade=5`。

| 材料 | 配置名称与用途 | 包内注明来源；尚非离线产出验收 |
|---|---|---|
| 503344 | 聚元玄晶，真灵升级经验 | 昆仑山掉落 |
| 503345 | 虚天灵元丹，融灵 | 活跃度宝箱 |
| 503346 | 极地灵元丹，融灵 | 决战黄泉路 |
| 503347 | 上古技能卷轴，主动技能升级 | 妖兽/荣誉商店 |

来源为 `item.json` 的原版描述。关卡实际掉落概率、次数限制、兑换成本与离线供应闭环没有因为这些描述而自动成立。

## 获取、请求与服务端边界

路由函数 `0x2a80af8` 使用 command 作为索引，半字跳表位于 `0x52092d0`，分支基址 `0x2a80b38`；分支将下列 action 写入请求。它不是单纯字符串清单。

| cmd | action | 对应操作 / 原标签 |
|---:|---|---|
| 457 | `truespiritopenbag` | `REQUEST_OPEN_BEAST_BAG` |
| 458 | `truespiritfusion` | `REQUEST_BEAST_MIX` |
| 459 | `truespirituplevel` | `REQUEST_BEAST_UPGRADE` |
| 460 | `truespiritupskilllevel` | 主动技能升级 |
| 461 / 462 / 463 | `truespiritrefreshimprove` / `truespiritrefreshskill` / `truespiritlearnskill` | 资质、重置/学习技能 |
| 464 / 465 | `truespiritchangetrione` / `truespiritopentrioneslot` | 悟性/根骨/灵力相关槽位与培养；具体各枚举 UNKNOWN |
| 466 / 467 | `truespiritchangeequips` / `truespiritunwieldequips` | 真灵装备穿脱 |
| 468 / 469 / 470 | `truespiritrefreshspecial` / `truespiritsettamestate` / `truespiritthrow` | 特殊属性、驯养/出战状态、放生 |
| 480 | `truespiritinfo` | 真灵信息，相关标签 `REQUEST_BEAST_SUMINFO` |
| 481 / 482 | `truespiritenhanceequip` / `truespiritraisedegree` | 真灵装备强化/升阶 |
| 792 / 793 / 794 | `beastrelicshome` / `beastrelicsenter` / `beastrelicsleave` | 真灵遗迹入口、进入、退出 |
| 856 / 905 | `truespiritevil` / `truespiritblood` | 特殊转化与血脉操作 |

前三项已同时核对 sender：`0x2bfd194..0x2bfd1bc` 明确 cmd 457 + OPEN_BEAST_BAG；`0x2c1696c..0x2c16994` 明确 cmd 458 + BEAST_MIX；`0x2c044e0..0x2c04508` 明确 cmd 459 + BEAST_UPGRADE。其余 action 数字由同一原生路由解析，未逐项完成回包契约。

**融灵有真实对象与材料交换，不能返回空成功：**

1. `0x2c166b0..0x2c16994` 构造 `rid`、`main_pet`、`auxiliary_pet`、`directed_material`、`evolution_material`、`green_type`、`is_common_fusion`，另有 `is_use_sheep` 条件字段。主宠对象含 `global_id/type_id`；完整 ABI 与所有条件字段类型待形成独立契约。
2. 共用 handler `0x2c189a0` 的融合分支在 `0x2c1932c` 调 `0x2c181fc`，该返回值会影响后续流程。
3. 该消费函数读取 `target`、`auxiliary_global_id`、`main_global_id`、`cost_material`、`return_material`、`user_back_privilege_return`、`return_tip`。`0x2c183d8` 调原生移除物品函数 `0x2d2916c`，`0x2c18480` 调原生入包函数 `0x2d41900`，`0x2c1876c/0x2c18790` 用真灵工厂构造结果。
4. 客户端具备应用结果的代码；**尚未证明客户端具备完整的权威抽样/继承/保底计算函数**。不能用一只固定真灵代替原融合。

特殊原生方法还包括 `requestBeastMechanismTransfer`、`requestBeastExtraUpgradeSkill`、`requestBeastMaxUpgradeSkill`、`requestBeastAddTalentSkill`（RTTI/lambda 名位于 `0x52110b0..0x5211200`）；其请求为 `truespiritdevil`、`truespiritdevilskilladd`、`truespiritskillfullval` 等线索。完整命令、回包、上限与材料规则仍为 UNKNOWN。

捕捉分支 `0x319e998` 检查对象虚函数 `+0x18c0`，与普通宠物捕捉分支分开；调用 `0x2c0f3ec` 在 PetMgr `+0x510` 区域累计按种类的捕获记录并移除场上对象。包内 `rule[71000145..71000147]` 明确阴阳二气瓶、遗迹天气/时段、捕获后进入点化空间。**该计数不是一只已归属角色的真灵**，点化结果及冷启恢复尚未验证。

## 角色数据、存档与对象构造

| 层次 | 原生证据 | 离线影响 |
|---|---|---|
| 普通宠物 | PetMgr `+0x258`；普通 serializer `0x2c1ab40` 输出 `petinfo/bagsize/maxglobalpetid` | r11 普通火丸路径只覆盖这里 |
| 真灵容器 | ROLE `0x2fefe0c..0x2fefe7c` 读取 `savedata.true_spirit_bag`；字段指针 `0x6784b78` | 当前 `validateSaveUpdate` 根白名单没有该模块 |
| 真灵加载 | `0x2bfca74` 清空 PetMgr `+0x298`，读取 `list`、`bagsize`，检查 `maxspiritid` | 清空后逐个恢复；丢字段/空 ACK 可使原数据消失 |
| 真灵工厂 | `0x2bfcc14..0x2bfcc64` 调 `0x3aad200()`、`0x3aad6d4(factory,json,null,null)`，成功对象加入 `+0x298` | JSON 项是完整真灵对象，不是 `A2/A4` 材料对象 |
| 基础身份 | `0x3aad6d4` 读取 `dataid`，兼容 `spiritid`；以 type 17 查配置，按 `YJPet%d` 工厂名选构造器 | 必须保留配置 ID 与全局 ID 各自语义 |
| 增量结果 | 原回包多处读取 `true_spirit.globalid` 后更新/替换对象；例如 `0x2c0ef70..0x2c0f280` | 单次变化与全容器快照必须有确定投影 |

完整真灵 JSON 字段、全部子类 serializer、dirty 位及更新后的可靠保存时机为 **UNKNOWN**。已确认 `maxspiritid` 被检查，不将它的值类型、分配规则或 setter 默认为普通宠物的 `maxglobalpetid`。不能直接添加白名单就宣称存档恢复。

## 属性与战斗

- `pet[9000]` 炽烈怒炎：固定基础 HP 25000、MP 12000、攻击 4000、防御 2980；成长范围、四类成长因子、`born_skill=[9000000,9000010,9000020,9000030]`、`ai_pet_9000` 均在配置中。`pet[9012]` 幻神雀、`9022` 玄武、`9043` 圣青龙有各自技能与血脉字段，不能以同一数值对象占位。
- 合体技能并非仅文案：`0x33174c8` 为按编号构造 `YJBeastArmorSkill%d` 的原生 factory；例如 RTTI `YJBeastArmorSkill9509` 位于 `0x5256860`。原生还含提高合体伤害/持续时间及压制时长的实际 Buff/Debuff 类型。
- `beast_armor_skill_desc` type 83 与宠物自身 `pet_skill` 分属不同数据；把“出战宠物技能”当作“角色合体技能”会遗漏战斗效果。
- 原生存在角色进入真灵状态事件 `YJ_EVENT_ROLE_ENTER_BEAST_STATE`。本次未完整追踪角色属性汇总函数、全部技能系数使用与每种真灵的完整战斗动画；这些仍为 UNKNOWN，需合法获得真灵后的实战验收。

## 资源完整性

本次检查三个 ZIP 的中央目录，以已验证加载规则 `skeleton/pet/%d.json`、缺失时 `.skel`、配套 `.atlas/.png` 核对基础组；46 个真灵配置均无非零 `resource_id` 覆盖。

| 资源范围 | 已确认结果 | 不能推导的结论 |
|---|---|---|
| 原新包 / r11 的真灵基础组 | 仅 9043、9044、9045 具备 `.skel + .atlas + 主 PNG`，3/46 | 不证明全部 atlas 分页、技能、变体动画已验收 |
| 原旧包平铺骨骼 | 9000–9008、9010–9016 共 16 组 `.json + .atlas + 主 PNG` | 是候选来源；未验证旧动画与新配置/类兼容 |
| 两包合并候选 | 上述基础组 ID 不重叠，剩余 27 个 ID 在此规则下仍缺基础组 | 不得用旧包替代品或改 ID 冒充原资源 |
| `ccbi/Beast` 完整路径引用 | 索引中 13 种完整路径均在 r11 | 不包括动态拼接路径与所有战斗资源 |

资源索引：[CCBI 引用](../artifacts/zmxol-offline/inventory-2026-10-12/ccbi-resource-references.json)、[动态路径族覆盖](../artifacts/zmxol-offline/inventory-2026-10-12/update-resource-coverage.json)。UI 图集存在不等于真灵可获取、保存或参战。

## 离线恢复判断与下一步

**可复用：** 原生对象与技能工厂、UI、已存在基础资源、配置属性/消耗/候选表、原生回包消费函数及 ROLE 真灵容器 loader。

**必须补齐：** 完整真灵对象 serializer 与 round-trip 测试；融合事务的输入校验、消耗、唯一 ID、结果、快照及幂等；升级/技能/装备/状态等逐项响应；来源玩法及材料闭环；资源缺项；捕获到点化再拥有的完整状态链。

**UNKNOWN 阻断：** 完整权威融合概率叠加与保底、特殊转化结果、完整冷启字段/ID 分配、各入口全部解锁条件、缺失 27 个基础组的合法来源、全技能与真机行为。客户端包含部分概率表，因此不能说“真灵概率完全缺失”；同样不能说“已有表就已还原服务端”。

建议以一个原配置组合完成“真实材料 → 原生成结果应用 → 真灵背包 → 合体实战 → 原快照 → 冷启相同”后，再按命令组扩展。确需自定义规则时需显式标为离线重建规则，不能计入原版逻辑还原。

## 可复用记录

| 内容 | 类型 | 范围 / 来源 | 失效或复查条件 |
|---|---|---|---|
| 普通 pet 与 true_spirit_bag 分开恢复 | STATIC | 15.7.2 ARM64；ROLE 与 PetMgr loader 地址见上；2026-10-12 | 更新 native 库、改变角色响应投影时重查 |
| 融合必须应用目标对象及材料交易 | STATIC | cmd 458 sender/consumer；2026-10-12 | 补齐完整回包与动态验证后修订字段表 |
| 资源覆盖仅为基础组/路径检查 | STATIC | 两原 APK + r11 中央目录；2026-10-12 | 新增资源、修改路径或加载器后重算 |

本次仅增加调查文档；无数据库/API/运行时代码变更，未执行真灵功能测试。历史普通宠物验收保留，真灵恢复仍未完成。
