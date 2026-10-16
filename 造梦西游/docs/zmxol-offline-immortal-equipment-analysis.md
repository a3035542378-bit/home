# 15.7.2 仙器子系统调查

更新时间：2026-10-12。范围：原 APK 配置、15.7.2 ARM64 原生实现、r11 文件及当前桥接。本文为静态调查，没有操作 ADB、改变存档、修改生产代码或执行仙器实机验收。

**结论：15.7.2 的仙器对应 `YJFairyEquipManager`、`fairydevice*` 协议和 type 12 高品级装备，并具有器灵、符印、词条、元神投影等实际分支。** 客户端含属性表、成本表、原生装备/技能工厂和结果消费函数；铸魂等操作仍需服务端式结果及材料交易。当前普通装备/宠物路径成功不代表仙器恢复，不能以普通 `A2/A4` 占位对象或空 ACK 完成。

## 依据与状态

- **STATIC** 指本次配置或反汇编证据，**HISTORY** 指旧工程记录，**UNKNOWN** 指缺少完整调用链或实测。
- 配置：[decoded/database](../artifacts/zmxol-offline/15.7.2/decoded/database)。原生文件 `/private/tmp/zmxol-revival-newer/lib/arm64-v8a/runtime-analysis-libgame.so`，本文偏移仅适用 15.7.2 ARM64。
- 已确认 [r11 APK](../artifacts/zmxol-offline/squad-build/15.7.2-gadget-r11.apk)、[历史冷启截图](../artifacts/zmxol-offline/15.7.2/r11-final-cold-start.png)、[主记录](zmxol-offline-revival.md)存在；没有重新执行其历史验收。

## 原生身份、入口及装备模型

| 层次 | STATIC 证据 | 限制 |
|---|---|---|
| 系统 manager | `YJFairyEquipManager` RTTI `0x5213730`，主虚表 `0x6055710`；铸魂 sender 与 callback 见下 | 并非仅 UI 文字命中 |
| 原生界面 | `YJFairyEquipBoardLayer/ForgeLayer/UpgradeLayer/EnchantBoardLayer/RefineLayer/RunyinLayer/EnlivenerLayer` 等类型 | 入口全部开放条件 UNKNOWN |
| 成品装备 | `noblest_equip.json` 119 行，全部 type 12；grade 8/9/10/11 各 47/23/25/24 行 | 不能把这 119 行全部叫仙器；该表也含至尊阶段 |
| 具体仙器 | `noblest_equip[1320]` 红莲室火棍：grade 10、角色 1、武器、需求等级 85，HP 1300/攻击 1560/防御 100/破邪 100、暴击/命中/伤害率各 0.2 | 装备等级要求不等于全系统入口开放等级 |
| 基础工厂 | type 12 经 `0x3c6b750` → `0x3c45534`；完整 loader `0x3c50124`、serializer `0x3c4d7b8` | 实例唯一 ID、继承属性、词条等不能丢失 |
| 进阶实例 | serializer/load 读写多个扩展字段；铸魂回包额外含 `stunt_info`，以 `global_item_id` 绑定真实物品 | `A2/A4` 只够表达物品种类/数量，不构成已还原的仙器实例 |

`rule[71000049]` 描述一飞及以上至尊装备或器魂铸魂、装备属性转换、二飞词条继承、升阶、元神投影、洗练等。该文本与原生 manager、协议、配置交叉吻合，但属性转换和完整概率公式仍需逐项代码核对。

与其他系统的连接有实证：`module_open_guide[909233]` 的荒古入口描述角色达到战力/灵根门槛，或拥有一件尊品仙器；`guide_step[900594]` 引入锻造师，`900597` 检测已拥有尊品仙器。不能据此把尚未完成的荒古/副职业分支计为仙器可用。

## 配置覆盖、获得及成长

| 配置 | 行数 / type | 作用与一个可核验例子 |
|---|---:|---|
| `fairy_device_composite_config` | 88 / 97 | 6900001：角色 1，503410×1 → 候选1320；基础消耗503413×100；另有第二组消耗与词条数/继承字段 |
| `fairy_device_ascension_quality_config` | 120 / 98 | 6910001：目标一阶，消耗503417×1、503415×5；有最低品级条件 |
| `fairy_device_enlivener_wit_config` | 9 / 99 | 6920001：总投影等级20的灵窍条件，增加属性类型1/3，数值4000/300 |
| `fairy_device_ascension_grade_config` | 15 / 100 | 6930001：消耗503424×80、503425×10；增加类型3/7，数值1300/0.15 |
| `fairy_device_enchant_basic_config` | 340 / 103 | 6960001：武器/角色1/品级10/生命属性；分段门槛及各级可用符文 |
| `fairy_device_enchant_attr_config` | 520 / 104 | 6970001：503429×1，属性类型1，`add_ratio=[20,100]` |
| `fairy_device_stunt_fixed` | 91 / 129 | 固定特技、效果类型、叠加、星级、经验及品级限制；7484000 对应体质/534000 |
| `fairy_device_entries_weight` | 99 / 151 | 主副词条数量、目标词条权重、保底数量与额外材料字段 |
| `vice_occupation_fairy_device_remove_skills` | 9 / 150 | 副职业移除特技相关配置 |
| `fairy_device_secondary_profession_task` | 4 / 105 | 副职业任务材料/目标 |

`fairy_device_enchant_config` 另有 16 行旧结构，不能把它与 340 行 basic 表合并成 356 条当前规则。原生库注册有 `fairy_device_enchant_basic_config.sdb`；各旧/新表的完整优先级为 UNKNOWN。

| 物品 | 名称 | 配置用途 / 来源描述 |
|---|---|---|
| 503410 / 503411 / 503412 | 武器/防具/饰品器魂 | 铸魂主材；极北之地 |
| 503413 | 冰魄寒晶 | 铸魂消耗，也被荒古神炼使用 |
| 503417 / 503415 | 下品仙玉 / 玉髓 | 升阶成本表；极北之地 |
| 503424 / 503425 | 天陨星晶 / 青莲炎 | 升品成本表；极北之地 |
| 503429 | 一级普通生命符 | 仙器附魔；符文师、交易所、活动 |
| 503515 / 503516 | 简易锻造锤 / 特技增幅石 | 分解仙器所得副职业材料 |
| 530203 | 器源真核 | 器灵分解产出、强化消耗 |

以上来源来自 `item.json`。原副本、商城/交易所、活动的完整离线产出尚未建立，不能因为成本表齐全就宣称经济循环齐全。

## 原生请求与响应应用

command/action 来自 `0x2a80af8` 路由函数、`0x52092d0` 跳表，不是按英文名称猜数字。

| cmd | action | 系统操作 |
|---:|---|---|
| 534 / 535 | `fairydevicecomposite` / `fairydevicecompositepreview` | 铸魂 / 预览 |
| 536 | `fairydeviceascensionquality` | 升阶 |
| 537 / 538 / 539 | `enlivenerhome` / `enlivenershadow` / `enlivenerfuse` | 元神入口、投影、熔炼 |
| 540 / 541 | `fairydevicebaptize` / `fairydevicebaptizeresultensure` | 洗练、确认结果 |
| 550 / 560 | `fairydeviceascensiongrade` / `fairydevicenchant` | 升品 / 附魔（原 action 拼写如此） |
| 693 | `fairydevicetransform` | 饰品转换 |
| 704 / 705 / 706 / 707 | `fairydeviceslotmark` / `fairydeviceslotupgrade` / `fairydeviceslotupgradestar` / `fairydeviceslotremove` | 符印刻印、升级、升星、移除 |
| 716–720 | `fairydevicedrawhome/draw/buy/goodslist/logs` | 仙器相关抽取、商城、日志；具体活动条件 UNKNOWN |
| 727 | `fairydeviceslotdecompose` | 符印分解 |
| 577 / 931 / 932 / 933 | `viceoccupationfairyresetstunt` / `viceoccupationremovefairystunt` / `fairydeviceforgebaptize` / `viceoccupationfairychangestunt` | 副职业重置/剥离/洗练/换特技 |

另有原生 `setEquipStuntStateByIndex`、`requestFairyEquipReplaceHome`、`requestFairyEquipReplace` 方法及 `fairydevicestuntseal/fairydevicereplacestunthome/fairydevicereplacestunt` action。完整请求字段/幂等语义未核对，标 UNKNOWN。

**已精确定位的铸魂闭环：**

1. `0x2c76d00..0x2c76f08` 构造 `rid`、`main_material`、条件性 `composite_num`、`from_type`、`league_vice_occupation_id`、`extra_material` 等，明确以 cmd **534**、tag **`REQUEST_FAIRY_EQUIP_FORGE`** 发送。不是普通制作书的本地 forge。
2. 注册 callback `0x2c89be8`；其 `0x2c89df0..0x2c89e28` 分支精确匹配该 tag，调用 `0x2c825f4`。
3. `0x2c825f4` 读取 `add_goods`、`add_fairy_device_list`、`remove_goods`，并处理次数等状态。`add_fairy_device_list` 经 `0x3d29634` 取成员名后逐项访问，**不能先假定它是 JSON 数组**。
4. 每项 `fairy_device` 在 `0x2c82ac8..0x2c82b00` 交给 `0x3c6b750`，再由 BagMgr `0x2d41900` 真正入包。
5. 每项可有 `stunt_info`，其中 `global_item_id` 必须匹配新装备虚函数 `+0xf0` 返回的唯一 ID，才在 `0x2c82c04..0x2c82c0c` 调 `0x3c3c600` 应用。仅显示装备图标会遗漏此结构。
6. 回调发出 `REQUEST_DATA_HANDLED/REQUEST_GO_ON` 后推动界面。未来离线实现应在通知放行前确认原生结果、材料扣除、ID 与完整快照原子提交，避免重复生成或冷启丢失。

`now_fairy_device` 确实存在，但属于 `0x2c768b*` 的另一装备更新路径：`0x2c76900..0x2c76930` 给 manager `+0x198` 对象的虚 loader `+0xc0` 更新。**不能把这个字段误写为上述 cmd 534 的唯一结果契约。**

## 存档及战斗影响

- 成品仙器是实际装备实例；通用 type 12 factory/完整 serializer 能处理装备字段。`A5` 为本地装备唯一 ID，另有 `UNIRID` 及扩展属性；参考既有[普通物品契约](../artifacts/zmxol-offline/squad-build/ordinary-level-lottery-contract.md)。不能靠重新创建 `{A2:1320,A4:1}` 保留原装备养成。
- `0x3c4d7b8` serializer 与 `0x3c50124` loader 有大量双向字段，如 `BG`、`CN`、`D9`、`E5`、`FK`、`GD` 等；本次没有把未知短码猜成品级/词条字段。**各字段语义、仙器全部养成是否都包含于 bag 以及辅助 manager 的冷启模块仍 UNKNOWN。**
- 原生铸魂载入的 `stunt_info` 由 `0x3c3c600` 处理；其下游包含 `saved/unsaved/unsaved2/ancient_saved/ancient_unsaved/slot` 状态，表明存在待确认与已确认的区别。洗练不能仅覆盖最后一个显示对象。
- `fairy_device_stunt_fixed` 有作用类型/数值/叠加定义；`noblest_equip[1320]` 有破邪、暴击、命中和伤害率。`rule[71000121]` 明确部分关卡对仙器/破邪有特殊要求。具体原生属性汇总、每条词条战斗效果与约束尚未逐项验收。
- 元神投影是依赖分支：`rule[71000049]` 说明穿戴相应部位仙器时投影生效；cmd 537–539 及灵窍配置证明客户端流程存在。独立存档、投影装备身份、熔炼后的保存契约 UNKNOWN。

## 器灵与符印等分支

器灵已被独立原生 manager 和技能工厂证实，不能只归为仙器图标：

| 证据 | 内容 |
|---|---|
| manager | `YJFairyEquipSpiritManager` RTTI `0x52128d0`，方法名包含 evolution/lightstar/wakespirit/setlinkskill/experiencelevelenter/leave |
| 当前物品表 | `fairy_equip_spirit` 22 行，type 146；7526000 微火灵，bag_type 5、最大星级5、最大强化10、分解530203×10 |
| 强化 | `fairy_equip_spirit_enhance_config` 270 行，type 148；7540000 强化1级，属性类型3增加360，消耗530203×100 |
| 技能/突破 | `fairy_equip_spirit_skill` 22 行，type 147；7527000 突破消耗同类器灵，`effect_value_1=[3,1000]` 与战斗内攻击+1000描述一致 |
| 原生战斗实例 | `0x320493c..0x3204984` 按 `YJFairyEquipSpirit%d` 选择工厂；7527000 有实际原生类型（RTTI `0x524db30`） |
| 旧结构风险 | `fairy_equip_spirit_config` 17 行也用 type 146，字段却不同；不能与22行当前物品表简单拼接 |

器灵全部 RPC、独立背包保存、装备链接、试炼奖励、觉醒/点星结果形状仍为 UNKNOWN。符印 cmd 704–707/727、特技配置及对应 UI 存在，但完整升星/分解事务同样尚未离线实现。

## 资源边界

复用本次全量资源索引：[CCBI 引用](../artifacts/zmxol-offline/inventory-2026-10-12/ccbi-resource-references.json)、[动态路径覆盖](../artifacts/zmxol-offline/inventory-2026-10-12/update-resource-coverage.json)。

- `ccbi/FairyEquipSpirit` 提取出15种完整路径引用，其中10种在旧包、新包及r11都缺失，包括 `spirit_bag/spirit_bag.plist`、`spirit_develop/spirit_develop.plist`、点星/觉醒动画图集等。
- r11 的 `roles/fairy_armor_effects/` 路径族为空，旧包该同路径有105个文件。仅是可评估补齐来源，未证明适配15.7.2全部职业和仙器。
- 静态类、CCBI 文件存在不保证图集、骨骼、粒子和着装特效齐全。全部仙器/器灵资源覆盖、atlas分页及实机渲染均 UNKNOWN。

## 离线可行性与缺口

可复用原装备模型、属性/消耗/候选表、原生交易回包消费函数和技能工厂；无需重写游戏战斗。优先恢复一个确定配方的原生铸魂流程，再逐项恢复升阶、升品、附魔、洗练与辅助成长。

必须先完成：原始装备输入/输出 schema；唯一 ID 与词条绑定；实际材料扣除；预览与提交分离；随机/继承算法来源；重复提交保护；原生对象完整快照与冷启恢复；配套资源及来源玩法。客户端含 `entries_weight` 等数据，因此“服务端概率完全缺失”不成立；**全部概率、保底、词条选择与继承公式已还原也不成立**。

本次没有生产补丁，没有仙器功能测试或数据库/API变化。离线实现、真机验收、完整资源恢复均未完成。

## r12 附注：502211 是普通制作书，不是仙器

该项服务于当前700003验收，不与仙器完成度混淆。

| 项目 | 原配置 / 存档证据 |
|---|---|
| 502211 | `forge.json`，type13/stackable1，通风灵戒制作书；`forge_by_server=0` |
| 产物 | `output_id=500201`；`equip.json` type12/grade2/饰品，HP100–120、MP90–110，可强化，不限制角色 |
| 原成本 | 玄铁502000×20、丝绸502002×10、灵魂1000 |
| 4451B 原快照 | `r11-after-pet-guide-save.json` 等：玄铁20、丝绸21、灵魂2145；没有制作书 |
| 4434B 最终快照 | `r11-final-after-restart-save.json` 等：同样材料、灵魂17145；没有制作书 |
| 判断 | 真实领取502211后材料足够，不需要追加材料、直接发成品或把recipe当装备 |

静态 loader `0x2db6698` 加载 forge 配置，`0x2db6990..0x2db69ac` 读取 `forge_by_server`，写配置对象 `+0x1e4`。type13的制作书使用基础物品对象，type12成品另走装备工厂。**具体原UI本地制作入口/协议分支及500201打造后的实测保存仍 UNKNOWN**，不能仅据 `forge_by_server=0` 宣称打造已恢复。

## 可复用记录

| 内容 | 类型 | 来源 / 范围 | 失效或复查条件 |
|---|---|---|---|
| cmd534实际消费add_fairy_device_list，而非只读now_fairy_device | STATIC | 15.7.2 ARM64 sender/handler/consumer；2026-10-12 | native版本变化或取得原请求回包后补证 |
| 仙器属于完整type12实例，特技按唯一ID绑定 | STATIC | 0x2c82ac8..0x2c82c0c；2026-10-12 | 更改装备serializer/快照投影时重查 |
| 502211是recipe，500201才是普通成品饰品 | STATIC | forge/equip配置与r11快照；2026-10-12 | 新版本配方或实际背包变化时重查余额 |
