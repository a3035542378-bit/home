# V5.2 真灵融合响应与实例存档验收

日期：2026-10-15；15.7.2 ARM64；专用 AOSP API 30 模拟器。没有重新扫描全部资源或调查攻略。

**已通过原版融灵操作获得一只强良兽，原工厂创建、材料扣除、独立真灵背包、落盘和断网冷启动已实测。结果生成器是明确隔离的固定兼容实验，不是还原了原服概率和继承算法。生产桥源未改，尚未交付正式真灵功能或新 APK。测试结束恢复原档与当前外置生产桥；融合结果保存在独立测试档和证据目录，不写入用户原档。**

## 准出层级

| 层级 | 当前结论 | 证据与限制 |
|---|---|---|
| A 融合响应 | 隔离兼容样例通过 | 原 UI 发 cmd458；原响应消费者与工厂成功；原完整真灵属性窗口显示列表、模型、75级实例。不是全配方协议实现。 |
| B 实例与存档 | 核心闭环通过；正式准出仍有限制 | 4407 实例持久化；100/100→98/94；源宠仅消费4405/4406，原五宠和普通背包不变；断网冷启恢复；受保护的重复消费诊断无资产变化。异常存储主要由替身测试验证，未完成真实断电、通用多次融合与多角色切换。 |
| C 完整真灵使用 | 未通过，独立阻塞已复现 | 原出战按钮发 REQUEST_BEAST_SET_TAMESTATE / cmd469，返回 success=0；UI 乐观改成“休息”，不能认作出战成功。未把此现象当作合体或战斗通过。 |

## 1. cmd458 原响应契约与调用链

分析使用既有恢复 ARM64 库与既有反汇编；地址不可跨版本套用。动态证据为 `artifacts/zmxol-offline/v52-20261015/`。

原 sender 的业务输入在 `0x2c166b0..0x2c16994` 构造。本轮实际输入：

```json
{"rid":10001,"main_pet":{"type_id":221,"global_id":4405},"auxiliary_pet":{"type_id":229,"global_id":4406},"is_common_fusion":1}
```

API 会补充角色、装备、日志与 savedata 等公共字段，不能把这些字段当成新的融合选项。实际附带的 savedata 为 bag/pet/mire/level/eggdata/roledata/interaction_data/novice_boot_task_progress，**没有 true_spirit_bag**。定向、进化材料、green_type、is_use_sheep 分支未动态验收；实验明确拒绝这些选项。

| 响应字段 | 原消费证据 | 本轮使用 |
|---|---|---|
| code | 公共响应链；本轮1000经原客户端成功处理 | 1000；不声称恢复全部失败码枚举 |
| target | 2c18244检查；2c18774读取；3aad6d4构造；18c0判断真灵后加至PetMgr+298 | 对象，使用29字段的9001原生序列化结构 |
| main_global_id | 2c186e4读取，经整型helper；非零时查找并移除主宠 | 整数4405，必须实际存在；不能用类型221代替 |
| auxiliary_global_id | 2c18260检查，2c1869c读取后移除辅宠 | 整数4406 |
| cost_material | 2c1827c起迭代，每项经3c6b750；可堆叠分支2d2ae04扣数量 | 数组 `[{A2:503345,A4:2},{A2:503346,A4:6}]`，已动态验证 |
| return_material | 2c183f0起迭代，经原物品工厂及2d41900入包 | 可选数组；本轮未发送、未动态验收返还 |
| user_back_privilege_return | 2c184b0起迭代，经工厂加入CCArray展示链 | 可选分支；不能据名称认定等同实际入包；未发送 |
| return_tip | 2c185ac检查，经3077eb0读取进入提示链 | 可选提示；未发送，异常类型未动态验收 |

关键链：

```text
原融灵界面 → 2c16994(BLR x6, cmd458)
→ 原API公共字段补充 → 原响应管线2ab75d8
→ 公共handler 2c189a0 → 458分支2c1932c
→ 原融合consumer 2c181fc
→ 移除源宠 / 原Bag扣材料
→ 3aad200工厂单例 → 3aad6d4(target,null,null)
→ 原对象配置/归属设置 → PetMgr+0x298.addObject
→ 原结果窗口及通知
```

target 存在时，原消费者会先移除主宠再创建目标，不能将未经工厂预检的 JSON 直接投递。实验先做工厂往返验证、原子保存 prepared 收据，然后才允许成功体进入原处理链。没有用空成功模拟第一次融合。

没有恢复原服全部失败响应。现有真实网络失败为 success=0；输入不支持、存储失败或状态不明时不提供融合成功体。无 target 的原消费分支也可能处理辅宠/材料，不能随意把它当作安全失败响应。

## 2. 真灵实例与独立背包

原 loader：`0x2bfca74`；ROLE读取 true_spirit_bag 并调用它：`0x2fefe0c..0x2fefe7c`。普通宠物在 PetMgr+258，真灵在 **PetMgr+298**。原9001实例 serializer为`0x3a67b30`；不是复制普通 petinfo。

该样本实际输出 **29字段**，更正工作中曾说32项的计数：

| 类别 | 字段 / 已验证形状 |
|---|---|
| 身份 | spiritid=9001（类型）；globalid=4407（实例） |
| 状态、成长 | level、exp、iselite、basepetid、tamestate：数字 |
| 资质 | hpimprove、mpimprove、strimprove、defimprove、comprehension、spiritpower、bonelevel：数字 |
| 基础修正 | opbasehp、opbasemp、opbasestr、opbasedef：数字 |
| 数组 | skill、triones、petequips、sageskillposition、passiveskill、talentskill |
| 等级映射 | opskilllevel、opsageskilllevel、sageskilllevel、tabooextraskilllevel：本样本null |
| 名称 | mastername：本样本空字符串 |

本轮正式取证的独立容器为 `list=[9001/4407]`、**bagsize=8**、maxspiritid=4407。容量从原 getter `0x2bf9930` 获取；早期试验曾临时写10，不能作为最终容量证据。原 loader 检查 maxspiritid，但已读取段没有将其作为客户端分配器使用。

ID方案仅限本实验：固定派生档、固定4405/4406源宠、预留未使用4407；生成与运行时检查冲突；写入 prepared 后禁止新的融合；消费响应只允许一次。不是通用ID分配器。生成器拒绝其他角色、已有融合收据及**任何既有true_spirit_bag模块**，保留旧档，不尝试迁移未知真灵旧档。

完整原窗口为 YJBeastInfoBoard：原构造26d07f0、init26d0ecc、vtable5fdd4d0。早期只打开Develop内层会透出城镇背景；最终DEBUG入口打开完整原“真灵属性”窗口。正式菜单注册/解锁入口尚未恢复，DEBUG不算正式入口。

## 3. 固定兼容结果的边界

仅允许 `--experimental-fixed-9001` 生成，还须设备存在 `DEBUG_ONLY_enable_fixed_fusion` 才准备响应。生产 `offline_bridge.js` 未加入实验逻辑。

- 原生默认9001对象经原serializer导出模板，再生成兼容目标；调用原JSON工厂再次预检。
- 固定类型9001；等级、资质沿用测试主宠；basepetid=221；四个技能为9001原配置born_skill；修正值沿用原模板零默认。
- 品质A来自9001原配置；模型为先前已准备的旧原包原字节资源。
- **不实现权威随机、保底、完整属性继承、天赋和血脉计算**。talentskill/passiveskill保持空；不伪造天赋。原融合预览HP18276，实验结果HP5700，差异明确保留，不宣称恢复原继承公式。
- 只验证结果应用、原生容器及持久化。非空装备/被动/天赋等未覆盖形状被实验校验器阻断。

## 4. 材料、事务与异常恢复

503345/503346属于bag_type=1；原普通背包serializer不输出它们。原查询链2d22be0使用受保护的类型ID，再查对应容器；不能裸调内部网格查找。实验从原对象虚函数+e0读实际余额，而非用存档A4冒充UI可用量。

同一个原子存档包含：普通Bag、普通Pet、独立true_spirit_bag，以及私有 `_DEBUG_ONLY_fusion` 收据（请求、唯一兼容结果、before/after原生快照和材料余额）。角色响应不包含私有收据。

1. 工厂预检不入包；准备阶段完整保存before和唯一响应。
2. 原处理函数实际扣费、消费两宠、创建并加入真灵。
3. 检查目标ID、材料差额、源宠消失、原五宠及普通背包不变，再提交after与committed收据。
4. 异常后阻断成功通知；应用后的任何快照/提交失败均锁住整个存储，防止普通SAVE把半提交状态写入prepared基线。
5. prepared冷启动保留before并阻断危险重试；committed冷启动恢复after。未实现通用自动续接/撤销，需要核对后从独立测试备份恢复，不能直接删除收据重试。
6. 两种材料从私有收据恢复，经原物品工厂/原入包函数；仅空余额可恢复，已相同则不重发，其他不一致阻断。范围仅两种测试材料、每种0–100。

普通背包与宠物快照使用JsonCpp原文本传回提交，避免JS Number舍入64位UNIRID；新增测试验证9223372036854775806原文保留。私有诊断对象不是资产权威快照。

| 场景 | 已执行验证 | 限制 |
|---|---|---|
| 重复请求 | 同一实际JS守卫：prepared/committed/未知收据均阻断 | 未做Android原始重复发送包 |
| 重复响应 | 相同JS守卫+原生空消费受保护诊断，实例仍4407、余额98/94、磁盘哈希不变 | 明确是受保护消费诊断，不是网络层原包重放 |
| 材料不足、非法实例 | 实际JS输入守卫测试：两种不足、缺宠、错类型/等级/状态、重复ID、ID冲突等 | 替身/纯JS，不是Android全部故障注入 |
| 提交前退出 | prepared→重建store，保留两源宠、空真灵容器、禁止新请求 | 存储替身测试 |
| 提交后响应丢失 | committed→重建store，仅一个结果且禁止重新准备；Android冷启也保持一只 | 未截断Android真实响应 |
| 写入失败 | prepare写失败、commit写失败、rename后目录fsync失败；校验实际持久阶段 | 文件操作替身，非实体断电 |
| 冷启动 | 原ROLE loader恢复29字段实例；材料原工厂恢复98/94；完整原窗口 | 专用ARM64模拟器 |
| 多角色 | 其他角色ID、请求rid被拒绝 | 单角色桥不支持真实多角色切换，不能称完整多角色隔离验收 |

模拟器本轮另出现退出137，原因未确认；同一AVD重启后测试档仍完整，但不据此声称通过真实断电测试。

## 5. 验收证据与回归

- `verified-fusion.log`：真实原UI请求、工厂预检、HTTP本地成功、原consumer执行、committed。
- `verified-fusion-result.png`：原结果页；`verified-fused-save.json`：经原消费者生成的独立实例。
- `guarded-response-replay.log`、`after-guarded-replay.json`：受保护重复消费诊断；磁盘哈希不变。
- `cold-with-materials2.log/json`：原工厂重载实例与98/94材料；早期完整闭环证据。
- `full-bag-probe.png`、`original-spirit-bag.png`：分别为完整窗口与早期内层窗口，不能混用为正式入口。
- `true-spirit-use-attempt.log`、`use-attempt.png`：原出战请求失败与乐观显示差异。
- 最终冷启动、源码hash、回归、原档恢复证据以同目录最终验收JSON及日志为准。

最终完整工具回归：**851执行、851通过、0失败、0错误、0跳过；新增55项；36.82秒**。不累加前一次850或历史796。自动化执行数与最终文件哈希在 `verification.json` 中记录；`regression.xml/txt`为实际回归输出。新测试覆盖生成边界、独立容器校验、原子阶段、int64、重复与非法输入；不将替身测试称为完整native/战斗验收。

## 6. 未完成与下一步

首要恢复cmd469：原sender在2bfe9fc发出469，构造global_id与state；共同handler的对应分支在2c19edc附近。需要确认成功体、乐观本地状态、ACK/回滚与独立真灵快照保存，再验证合体、技能、战斗及结算。当前出战失败后未继续冒认战斗成功。最终技能页显示惊怒扑击、狂怒挥砍、血腥吸引等主动技能为LV.0；四个配置技能ID被识别，不等于已激活或能实战生效。

之后才是权威结果计算、通用ID分配/多次融合、真实故障注入、多角色、正式入口和测试APK。未构建新APK：实验仍依赖显式测试档与激活标记，正式规则和使用闭环未准出。两个原APK、既有签名稳定包、Lua附加参考和QQ后端均未修改；无数据库或公共API变化。

最终取证：`delivery-cold.log`、`delivery-cold-bag.png`、`delivery-skills.png`、`delivery-469.log`。融合档/重复诊断后/最终冷启动/469失败后均为27045字节，SHA-256 `b9654463e319957e93be3b6f36a291a52e7572f8f418df46fffd23649b5e4cd9`。恢复原档11810字节，SHA-256 `be82335f783e733a207818a37bfc43de0857618c35b8bdae5fc7b1e7f6149fcb`；外置生产桥 `50bf21c36cf0ac6bce7a30297ec35d9df981c1aeafcfa4d7e012bad6dda8d95c`。原APK内置桥未重打包，不把外置验证当新APK准出。
