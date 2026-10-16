# 15.7.2 装备觉醒常规契约

日期：2026-10-14。结论：四个原生sender及费用/结果消费分支已补证；常规培养实施仍BLOCKED。未把教学免费或战斗触发概率当点火规则。

## 原版证据

分析源为15.7.2 ARM64 `runtime-analysis-libgame.so`，SHA256 `f218862955845f917e882c18bc7c100255f8cdf43c20d8558e03cb3949ecc7b0`。使用指令、原字符串及RELA→GOT指针链定位，llvm-objdump显示的最近导出符号名不能当函数身份。

| 动作 | cmd | sender发出地址 | 实际读取请求字段 |
| --- | ---: | --- | --- |
| 开槽 | 202 | 0x29efb28 | rid、goods_id、global_id |
| 充能 | 203 | 0x29effb8 | rid、goods_id、global_id、type、fire_global_id、fire_goods_id、energy_times |
| 点火 | 204 | 0x29f03f4 | rid、goods_id、global_id、fire_goods_id |
| 嵌石 | 205 | 0x29f08c0 | goods_id、global_id、type、rid、fix_goods_id、fix_global_id |

原标签依次为OPEN_AROUSAL_SLOT、CHARGE_ENERGY、FIRE、FIX_STONE，完整前缀REQUEST_AROUSAL_。共同通知consumer为0x29f1890。字段存在不证明全部参数类型、枚举、归属校验或成功回包完整。

点火consumer在0x29f1c48–0x29f1c5c匹配标签；0x29f1c68调用0x29f1184检查并遍历cost，执行原材料处理。返回false跳0x29f1f7c进入原错误对象构造，原文“发生不可预知的错误”（0x5206b40）。true后移除observer，调用0x2fe93b8/0x2fea720原通用应用；0x29f1ca8/0x29f1cbc读取result，0x29f1cd0比较是否1并分不同通知。原逻辑不是空成功ACK；0x29f1d20/0x29f1d34属于别的分支，不能混作点火结果。

原始证据：[manager反汇编](../artifacts/zmxol-offline/v3-20261014/awakening-manager-disassembly.txt)、[字符串/重定位](../artifacts/zmxol-offline/v3-20261014/awakening-literals-relocations.txt)。

## 配置与历史运行事实

equip[1307]为悟空虬龙棍/type12/grade6。arousal_stone[502554]为非堆叠type11，地图技能6300004、PK技能6300024。arousal_skill[6300004]为ATTACK_WITH_EXTRA_DAMAGE_MP_BY_PERCENTAGE，probability0.1/deltaProbability0，基值0.03/delta0.01/cd1。**0.1是战斗触发配置，不是点火成功概率。** 完整等级计算与实际战斗效果未证。

历史awaken-after-guide.json实际读取到装备4413第一槽C5=1，嵌入4415/502554、C2=2/C3=100，其余槽C5=-1；这证明完整实例已保存，不能仅凭短键猜完所有字段语义。本轮没重跑17步教学，也没执行常规点火或消耗。

## UNKNOWN与实施门禁

| 契约 | 现状 |
| --- | --- |
| 入口、解锁及装备类型校验 | 历史教学UI有证据；常规完整native校验UNKNOWN |
| 等级/阶段上限 | 需对照常规UI和原校验，UNKNOWN |
| 正式费用/数量、充能次数、开槽费用 | 有cost消费形状；权威数值与计算UNKNOWN |
| 点火成功概率/随机 | UNKNOWN；不得引用其他版本或技能probability |
| 失败后的等级/能量/返还 | 有result分支；完整失败状态UNKNOWN |
| 属性、实际效果 | 原配置有值；调用顺序、等级计算和实战UNKNOWN |
| 存档 | 完整bag教学保存已证；常规dirty位及多资产提交点UNKNOWN |
| 幂等/中断/写盘失败 | 尚无常规操作事务与回包重放证据 |

本轮不实施常规扣费或自定义概率。下一步对原面板只读预览，追cost来源、result合法枚举、准确字段类型、全SAVE/dirty位；确认同一实例与材料原子提交后才实现一条常规路线。重复请求、材料不足、超限、强退、存储异常及实际战斗/冷启必须单独验收。

证据标记：上述指令和配置为本版STATIC；教学存档为已读取的HISTORY；没有使用其他版本数值；其余明确UNKNOWN。数据库/API无变化。
