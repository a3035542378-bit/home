# 晴天脚本第三方交叉验证

日期：2026-10-14；目标15.7.2 ARM64。仅读取源码，没有执行Lua、授权、动态加载或写内存。原附件SHA256：`4d619e2e3d27a25c42651f174cdfcd09b4f3582b7dd1d641782e272648e779ed`。

| 函数/位置 | 第三方语义 | 原工程交叉映射 | 结论 |
|---|---|---|---|
| Pets/loadPtes，4227/4233 | 等级、HP/MP/攻击/防御资质；根骨/悟性/灵力；技能、涅槃与出战 | 原普通petinfo的level、hpimprove/mpimprove/strimprove/defimprove、bonelevel/comprehension/spiritpower、skill/triones/tamestate；已验普通serializer0x2c1ab40 | 字段语义可参考；不证明内存位置相同 |
| restCW，2855 | 从排行榜/奇闻录对象复制指针至自有容器 | 原native拥有独立普通宠与真灵容器、实例ID和归属 | 不具备合法实例创建、ID分配、存档事务证据，不迁移 |
| fission，4164 | 重复写同一指针、改变长度和容量 | 本轮材料工具按独立petid分配新普通实例，保留原实例 | 指针重复不是自然融合或合法复制；原脚本循环还有计数边界风险 |
| AdvancedProperties，2973 | 强化、至尊星/品、传承、阶数、进阶经验、仙器品/阶等 | item配置与原装备/仙器专项调查 | 只建立语义线索，hashMap第N项不是稳定字段契约 |
| initdata，3158 | 背包容器迭代、名称与类型分类、后续改写数据 | bag.item / 原ItemFactory及完整物品结构 | 不用其32位指针遍历替代原对象工厂 |

Pets的`0x354/0xF40/0xFA0/0x10D8/0x10E4/0xE9C`、根`m43995C`及Articles各offset全部为 `UNVERIFIED_OFFSET`。源码使用4字节指针步长与`&0xFFFFFFFF`，是32位适配线索；不能据此确认其准确版本，也不能迁入ARM64。

技能书学习技能、原生born_skill、随机被动、真灵天赋和合体技能分别取证。第三方向固定内存填技能ID不能证明官方技能继承。当前原UI声明辅宠不影响融合后宠物属性，但完整主宠继承公式及技能消耗仍待原native/回包验证。
