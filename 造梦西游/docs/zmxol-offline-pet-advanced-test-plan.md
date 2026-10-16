# 宠物丹药、八卦与本地 Mock 邮件验收方案

更新时间：2026-10-12。适用版本：15.7.2 Android ARM64。类型：已核实的配置、原生契约、candidate05 实机观察与待执行验收。依据为当前 APK 的 decoded/database、runtime-analysis-libgame.so、r12-task-route-save.json，以及本文列明的实机日志和存档；修改库、物品模型、协议或存档后复查。

用户已经授权通过 Mock 邮件发放宠物测试物品。本方案只建立本地邮箱，不接外部邮件服务；赠品标题和发件人必须明确写出 Mock。它是新增验收分支，不取代 700003 自然战斗、翻牌、制作书打造的原 r12 验收，也不能用于证明关卡实际会产出这些物品。

2026-10-12 新增明确授权：通过原邮件发送一只独立的 60 级最终形态宠物。火丸链 `210→211→212→213→252` 中，213 烈焰金刚仍有 evolution_id=252；真正末端为 **252 圣佛邪君，stage=5、evolution_id=0**。第三封本地邮件为 `900000252`，私有收据 `_offline_mock_pet`。本次实现只新增赠品，不提升已有 pet4399 的等级，不代表自然进化通过。生产代码及替身回归已完成，真实领取、资源表现、冷启与培养仍由主线程验收后更新。

**当前结论：candidate05 原邮箱已领取 Mock 504100×1，receipt=committed，真实背包数量为 1。Lv1 火丸第一槽选药是本地暂选；关闭培养后原流程自动返还，原 SAVE 成功，背包仍为 1，正式 triones 仍为 [1,1,0,0,0,0,0,0,0]。这条流程无需新增 cmd474 生产补丁，也不代表正式培养、属性增长或超进化已通过。** 邮件与背包冷启一致性待主线程完成；八卦使用及实例持久化仍未实测。Mock 赠品不能计入自然关卡掉落结果。

## 物品与实际子系统

| 项目 | 原表和类型 | 最小测试样本 | 已核实作用与边界 |
| --- | --- | --- | --- |
| 涅槃丹 | pet_pill，48 条，type 26；RTTI YJPetPillData、YJPetPillItem | 504100 攻、504101 防、504102 血、504103 魔，各 1 个 | 优秀品质分别增加对应资质上限 400；不是直接给当前攻击/生命加 400。配置明确在宠物培养中使用，超进化后可继续添加。 |
| 根骨、悟性、灵力丹 | 同表 | 504104、504105、504106，各 1 个 | 优秀品质分别增加对应上限 1。pill_type 5/6/7；不同于普通技能丹等 petusegoods 消耗。 |
| 八卦配件 | pet_equip，24 条，type 27；RTTI YJPetEquipItem | 504200..504207，各 1 个 | equip_type 1..8，依次乾、坎、艮、震、巽、离、坤、兑。配置说明超进化后装备八个不同配件激活八卦。 |
| 八卦套装效果 | pet_suit_effect，type 68 | 6605001 优秀、6605002 精良 | prop_info 按强化档位记录属性比例。6605001 档位 0 包含 str/def 各 0.1；不能脱离原装备数量、档位判断直接给宠物套上该效果。 |

八卦第一组基础随机范围：乾 HP 80..100；坎 MP 40..50；艮攻击 10..15；震防御 5..10；巽闪避 0.01；离暴击 0.01；坤回血 1；兑回魔 1。每件还有强化及升阶增量。504208..504215 是同品质另一组，初始强化范围 0..3；504216..504223 是精良。初轮选 504200..504207，减少额外强化状态。

实际基线 r12-task-route-save.json 中 `pet.petinfo[0]`：dataid=210、petid=4399、level=1，triones=[1,1,0,0,0,0,0,0,0]，petequips=[]，maxglobalpetid=4400。pet 表 210→211→212→213，stage 依次 1..4；213 为烈焰金刚。表中有超进化目标不等于已满足原生进化条件，不得把测试赠品默认为已进化或伪造自然养成完成。

## 独立最终形态宠物邮件的原生路径

已验证静态契约：`0x2afad8c` 的 `reward[]` 无须额外 `pet` 根字段。奖励项使用完整宠物 JSON 的 **dataid**，不使用 A2/A4；`0x3c6b750` 在无 A2、dataid 对应 type17 时，`0x3c6ba44→0x3aad200/0x3aad6d4` 创建原宠物，再由 `0x3c93be0` 包装为 YJPetItem。普通列表预览 `0x3c96fb0→0x3c970e8` 也会回到同一 full factory。type24 宠物蛋不是此次交付格式。

原领取 `0x2d41960` 的 type17 分支在 `0x2d41c44` 通过 `0x3c93dd4` 解包宠物；`0x2d41c4c→0x39f78f4` 从 PetMgr 原分配器 `0x2c1a9b4` 获取新 ID，并置 dirty bit4。之后设所属 manager、`0x2d41c80→0x2c031bc` 追加到现有列表；`0x2c03324..28` 是 CCArray append，`0x2c032ec..f0` 将新宠物置为休息 state2，`0x2c03304..1c` 使用当前角色唯一标识设 owner。该链不会调用先清旧列表的 ROLE loader `0x2c1ae44`。

本地 Mock 固定参数取 pet[252] 原表下界：basehp/mp/str/def=150/100/10/2，hp/mp/str/defimprove=600/600/600/200，悟性/灵力/根骨=1；level=60、petexp=0、lifetime=100、休息2，无装备，无已装丹药。技能按原 born_skill 为 210000/210010/210020/210030/210040/210050；默认两个开放空培养槽。此为明确测试参数，不声称还原原服随机品质或自然养成结果。基础战斗数值仍由 `0x3a18cb8` 原 loader 按252配置和等级重算。

预览模板 petid=1 是未入库对象的非零占位值，防止 `0x3a19c60` 因缺 ID 在浏览邮箱时提前分配；真正领取仍必经 `0x39f78f4` 重新分配。master_unique_rid 从当前原角色虚表+0x98读取。工厂输出经原单宠 serializer `0x3a0c618(x0=pet,x8=Json输出)` 固化，再经同一 factory/serializer 往返核对所有字段；原 virtual+0x1800 必须返回 stage5，预览前后真实 PetMgr 全量内容不得变化。

事务执行：原单封请求 savedata 与同次真实 pet/bag 快照先合并提交为 claiming；原 handler 真正追加后，在原 ACK `LR=0x2afc4fc` 前读取完整 PetMgr。必须恰好多一只、ID不冲突且新 watermark 大于新ID、附件字段一致、每只旧宠物逐字段不变、bag及point不变。随后 pet、bag、point 和 committed 收据一次原子落盘，才允许原 ACK、clear、GO_ON。背包满、原发奖未成功、属性变化、快照/文件失败都不能回成功；已提交收据不再出现在邮箱，冷启仅由已有完整ROLE宠物快照恢复，不能再次发奖。

测试边界：`test_offline_mock_pet_mail.py` 使用原生产JS+文件/Json/native替身，覆盖预览无入库、原生领取时序、旧火丸不变、重复领取、claiming重试、目录fsync失败后防重、容量和唯一ID、附件/属性异常及原生指纹。它证明本地事务代码，不证明252资源、真实客户端序列化或战斗已通过。

## 邮件列表与领取契约

地址均为分析库 VMA；运行时需加模块基址。

| 功能 | cmd / tag | 已核实原入口 |
| --- | --- | --- |
| 当前邮件列表 | 552 / REQUEST_REQUEST_MAIL_LIST_NEW | sender 0x2af5518；loader 0x2af7e6c；dispatch 0x2afc684 |
| 旧邮件列表 | 139 / REQUEST_MAIL_LIST | sender 0x2af53d0；loader 0x2af23b8 |
| 单封领取附件 | 14 / REQUEST_MAIL_RECIEVE_REWARD | sender 0x2af3834；dispatch 0x2afc4b8；reward handler 0x2afad8c。RECIEVE 拼写必须保留。 |
| 删除 | 140 / REQUEST_MAIL_DELETE | sender 0x2af5740；不纳入初轮领取范围。 |
| 一键领取 | 553 / REQUEST_REQUEST_MAIL_CLAIM_ALL | 本轮仅确认请求族，完整批量事务未核实，不默认支持。 |

新列表请求为 rid、type、offset，部分分类附 owner_type；sender 把 type 上限限制到 2，而 owner_type 来自输入分类减 1。真实 UI 在 0x21741a4 使用分类表 0x51ad0e0=[3,2,1]。0x2174e90..0x2174eb8 从 0x5e59090 取三组 active/inactive 图片名称，可将界面分类与请求准确对应：

| 原 UI 分类图片 | sender 分类输入 | 请求过滤字段 |
| --- | --- | --- |
| role_reward_mail | 3 | type=2、owner_type=2，角色奖励 |
| account_reward_mail | 2 | type=2、owner_type=1，账号奖励 |
| system_mail | 1 | type=1，无 owner_type，系统邮件 |

初轮仅在当前本地角色的角色奖励列表返回赠品，其余分类返回各自空列表。MailObj.mtype 并非这里的 type：它由对象保存为 uint8，领取时原样上送；目前没有证据确定原服务器各 mtype 数值的业务枚举。本地 Mock 可明确采用 mtype=0、MailObj.type=0、is_user=0，并严格核对领取请求一致，不能宣称这些值恢复了原服务器分类。

响应列表字段为 `mails:[]`、`total_page_num`、`offset`。0x2af7e6c 清空管理器旧列表后逐项创建 MailObj 并加载；offset 读入后加 1 用于 UI 页码。后两项可省略，但会保留旧分页字段，因此单页 Mock 明确给 total_page_num=1、offset=0。成功码、真实 point 应沿用当前已验证的网络响应公共层；列表请求本身没有调用 full savedata builder。

MailObj loader 0x2af8054 接受以下字段：

| 字段 | 原读取方式 | 本地测试定义 |
| --- | --- | --- |
| id | asString 后 atoi，存入整数 ID | 稳定的十进制字符串；只属于本地账号的 Mock mail ID。 |
| title / from / desc | 字符串 | 例如 `[Mock] 宠物丹药验收赠品`、`本地离线测试`；说明非自然掉落。 |
| mtype / state | 整数转 uint8 | 必须在首次原 UI 验证前固定本地定义，不能冒称恢复原服务器业务分类。state=0 在 0x2173518..39dc 显示未读信封，非零显示已读图标。 |
| expired / dateline | 过期时间为整数读入后 int32，日期为 int32 | 合法的当前时间与未来测试期限；避免溢出到 2038 年后。 |
| is_user / type | 整数 | 本地系统测试信的元数据；type 59/60 使用不同预览分支，初轮不借用这两个特殊类型。 |
| reward | 物品 JSON 数组 | 列表预览和领取必须引用同一份已经固化的附件对象。 |

MailObj.reward 在 type 59/60 时调用 full factory；其他类型调用 preview factory 0x3c96fb0。**预览有图标、名称和属性不能证明附件可以真实入包。** 当前协议目录未发现独立 MAIL_READ tag；已核实的 MailObj/条目展示是本地读取。是否还有打开即上报的通用请求，应由首次原 UI 抓包确认，不能凭“未发现标签”断言完全没有。

单封领取请求在 0x2af3874 调用一次原 full builder，随后写：`id`、固定 `type:37`、`mtype`、`offset`、`is_user`；userdata 也绑定 mail ID。**cmd552 的 rid 是 JSON 数字，但 cmd14 的 rid 是 full builder 留下的字符串**（0x2fe1bc4 调 std::string Json 构造）。cmd14 id/type/offset/is_user 为 Json::Int，mtype 为 Json::UInt（0x2af3928），初页 offset=0。0x2af39dc 将 mail ID 符号扩展到 x4，0x2af36e4 直接存 request+0x60；响应虚表+0x70 返回的 userdata 是此 ID 数值，不是 MailObj 指针。这个固定请求 type=37 与列表 MailObj.type 是不同用途。必须先保存这份自然请求携带的 savedata，再允许原 ACK，不能再调 full builder 补快照。

领取响应处理证据：

- 0x2afb334 将 reward[] 元素交给 full factory 0x3c6b750。
- 0x2afb35c 调用 0x2d45d04；该包装器核对 x0==x2 后，设置 w4=1/w5=0 并尾调用原 BagMgr::add 0x2d41900。这是实际发奖路径。
- 同一 handler 还会再次构造用于展示的物品，因此只给 A2/A4 的随机装备可能在不同构造中改变属性。应复用同一完整附件序列化对象。
- 后续按 `mails` 更新列表，也可读取 total_page_num、offset；特殊邮件读取 smail/mail_type。初轮不实现特殊邮件业务。
- 0x2afc4b8 分派领取 handler 后，依次调用 0x2fe93b8(root)、0x2fea720() 清理上传状态，再走完成通知。
- 原领取循环没有以 BagMgr::add 的布尔返回值作为“整封全部入包”证明。离线实现必须校验实际背包增量与附件一致，再提交领取 receipt；背包满、工厂失败或磁盘失败均不得标成已领取成功。

单封最小响应业务体可为 `reward:[{A2:504100,A4:1}], mails:[], total_page_num:1, offset:0`，另带公共成功码与真实 point。`mails` 是领取后该页完整剩余列表，不是增量：0x2afaec4 无条件清旧列表，0x2afb104 再按数组重建。仅更新 mails 也会结束 handler，但没有发奖，不能当领取成功；MailObj.type=0 不进入 type=1 的 smail 更新分支。

领取事务外层入口为 **0x2afba4c(x0=manager,x1=NetResponse/CCObject)**。单封分派在 0x2afc4ec 调用 0x2afad8c，返回地址 0x2afc4f0；接着 0x2afc4f8 ACK、0x2afc500 清上传状态，再直接到 0x2afbe2c 发送 **GO_ON**（返回地址 0x2afbe30）。这条分支不经过 0x2afbe18 的 REQUEST_DATA_HANDLED。不能仅在内层领取 handler 拒绝重复，然后让外层继续 ACK/清理未保存变化；重复响应与失败事务需要在确切请求的外层边界处理。

## 出战请求失败的最小修复边界

来源区分：主线程实测 700003 火丸死亡、原还魂教学后，REQUEST_PET_SET_TAMESTATE 返回 success0，但本地 tamestate 已成为 1；“quantity=0 时教学还魂成功”只是当前教学观察，不能外推为普通免费复活规则。以下时序已由原库确认。

- **cmd478 / REQUEST_PET_SET_TAMESTATE**：sender **0x2bff884(x0=PetMgr,x1=pet,w2=state)** 只构造 `rid:int,pet_id:int,state:int`，没有 savedata；0x2bff9d0 发出原请求。
- 出战 state=1 在发请求前已生效：UI 0x24ec624 调用 **0x2c067ac(manager,pet)**，后于 0x24ec670 发请求。前者在 0x2c067f8 调用 **0x39f7c68(pet,1)**，setter 0x39f7c7c 写 pet+0x1390；随后遍历两组宠物，把其他 tamestate==1 改为 2（0x2c06920/0x2c06940）。必须保存整个宠物列表，不能只改目标宠物的旧存档字段。
- 原成功分支 0x2c19f24 比较 tag，匹配后走 0x2c19ef4：移除 REQUEST_DATA_GOTTEN observer，0x2c19f1c 发 **GO_ON**。不读 result/petInfo，不调用 savedata ACK 或 dirty 清理。协议业务体最小可用 code=1000；离线端应在回成功之前把同次真实 PetMgr 全量快照原子保存，并核对目标 pet_id 存在且 tamestate=1。
- 最小保存入口：PetMgr singleton **0x2c1348c**、full serializer **0x2c1ab40(x0=manager,x8=Json输出)**，无需二次 full savedata builder。保留当前经验、寿命、还魂结果、其他宠物退战状态及 petinfo/bagsize/maxglobalpetid；保留存档其他模块，不用旧宠物对象覆盖新状态。
- **state=2 有不同时间边界**：sender 0x24ebe14 之前未设置 2；UI 注册 WAITING_STOP 回调 **0x24e8344**，成功无错误对象时在 0x24e8464..0x24e846c 才调用 setter(pet,2)。因此首补只开放实测 state=1。退战不能套用 sender 前快照后立即 ACK，需另在真实状态写入后保存。

2026-10-12 入口纠正：原先把自然 cmd478 模拟为 `0x2ab9290` constructor 路径的判断不成立。candidate03 自然出战 success0，且没有 prepared/rejected 日志；静态核实 `0x2bff9d0` 取 NetMgr 主虚表+0x58→`0x2ab7c78`，再+0x50→`0x2ab8770`。该路径没有 request 返回值，在 `0x2ab8c70` 调用 `0x2a7d980(x0=NetMgr,x1=request)` 入队，随后 release。现修复绑定原 sender、`0x2ab7c78` 的线程上下文和入队 LR=`0x2ab8c74` 的真实 request；`store.capturePet` 校验完整结构、唯一 petid 与目标 tamestate=1，再用原生 Json 值复制提交整个 pet。不二次 full builder。专门测试现为 36 项通过，已改为真实调用顺序，并增加旧错误入口不命中、入队线程/LR隔离回归；原31项通过只证明替身逻辑，不能作为入口正确证据。仍待主线程记录修正版自然请求、success1 与冷启状态。

## 原生物品工厂可以复用的范围

丹药 type 26 为可堆叠物品；A2 是配置 ID，A4 是数量。504100 经 0x3c6ac84 默认分支到 0x3c6abec，安装基础 YJItem 虚表 0x65c6f90，共用已验证材料的 JSON loader。0x3c667a0 仅让 type12 继续随机属性初始化，26 直接返回；0x3c63524 仅为 type24/12/27 分配唯一 ID，26 不进入。因此第一封丹药可以固定 `{"A2":504100,"A4":1}`，无需猜 A5；原列表与领取复用此同一附件。candidate05 实际领取已核实 full bag.item 中出现同一裸对象且 receipt=committed；生产提交断言仍必须核对 A2=504100 的累计 A4 恰好增加 1，不能仅凭工厂返回成功提交。

八卦 type 27 的可复用链：

`0x3c6b750(Json*) → 0x3c6b2e4 → 0x3c6ac84 → 0x3c84fd4(PetEquipData*) → vtable+0x3f0=0x3c82268 → 0x3c640cc → vtable+0x3d8=0x3c83098`。

0x3c83098 创建属性容器，读取原 PetEquipData 的 min/max，通过 0x3d4e7a8 生成基础属性。例如 0x3c831dc..0x3c833cc 读取首项范围、取随机值、写入基础属性。可以让原工厂生成一次，再用 `vtable+0xb8 = 0x3c85cac` 序列化；ABI 为 x0=item、x8=24 字节 Json::Value 输出。该 serializer 还写 AQ/AT/AV/AW 等完整字段。**不能由 JS 只猜 A2/A4/A5 就宣称完成八卦实例。**

待实测边界：工厂生成的 A5 初始值、BagMgr 在此邮件分支是否自动分配唯一 ID、完整序列化后再次加载是否保持八项属性和 ID、背包满的实际返回行为。普通装备已有证据不能直接套用于 type 27。应在隔离测试存档中完成“工厂→序列化→重建→入包→冷启”对比后才发行八卦附件。

## 丹药和八卦的使用协议

| 操作 | 请求 | 回调消费与原生计算 |
| --- | --- | --- |
| 涅槃丹已知网络分支（当前 UI 未命中） | cmd474 REQUEST_PET_CHANGE_TRIONE；sender 0x2bff070，savedata/rid/pet_id/trione_id/target_index | handler 0x2c03794；按 global_id 或 pet_id 找原宠物，`result` 交给宠物虚表+0x1510；`cost_goods` 单物品对象经 full factory、0x2d2ae04 扣背包；可有 return_goods 返还旧丹药。 |
| 其他宠物消耗品 | cmd288 REQUEST_PET_USE_GOODS；sender 0x2c0915c，savedata/rid/petid/goodsid | handler 0x2c094a4 必须有 petInfo，交虚表+0x1a60；cost[] 经 full factory 逐项扣数量。设置 pet dirty bit4、bag bit2。不要把此接口和涅槃丹槽混为一类。 |
| 装备八卦 | cmd475 REQUEST_PET_CHANGE_EQUIP；sender 0x2c05164，savedata/rid/pet_id/equip_id/equip_item_id | equip_id 是配置 ID，equip_item_id 是物品实例 ID。handler 0x2c0252c 用 result 更新宠物，随后按请求缓存的实例 ID 从背包移除；可有 return_goods 返还被替换的装备。 |
| 卸下八卦 | cmd476 REQUEST_PET_TAKE_OFF_EQUIP；sender 0x2bff368，同样含宠物与装备两类 ID | handler 0x2c00eec 用 result 更新宠物，return_goods 经 full factory 回到背包。不能单纯复制物品，需保留原 A5。 |
| 开启更多培养槽 | cmd47 REQUEST_PET_OPEN_TRIONES | 0x2bfd9d0 确认命令；涉及 petindex/index 等字段。价格、解锁资格和消费尚未完整核实，初轮只用原存档/原 UI 已开放的槽。 |

**空成功 ACK 有实际丢物风险：** cmd475 handler 允许缺 result 继续执行，并会消费请求中缓存的实例 ID；这会从背包删掉八卦，却没有在宠物身上装备。不得以“handler 返回 true”当功能成功。

宠物 result loader **0x3a1a188**，对应虚表 +0x1510，证据不止字段命中：

- 0x3a1a9a8 清空旧 triones，再逐个载入数组整数。值大于 1 时查实际配置，dynamic_cast 到 `YJPetPillData`，0x3a1aaf0 调用 **0x3a045d8**，从原丹药配置累加三项整数上限和四项浮点资质上限。0/1 不走物品效果；结合原开启函数和 candidate05 已确认 1 为已开启空槽、0 为未开启槽。
- 0x3a1a2d8..0x3a1a440 依据原 pet 配置、宠物等级和当前资质重算 HP/MP/STR/DEF。无需在 JS 重写战斗公式。丹药改变的是培养上限，实际资质未变时不能要求战斗面板立刻增加对应数值。
- 0x3a1a5b0..0x3a1a5f8 处理 petequips，先清旧数组再按传入完整物品恢复，随后 0x3a1a600/608/610 调用原装备相关重算。
- 单宠物 serializer 为 **0x3a0c618**（x0=pet，x8=Json 输出）；0x3a0cc4c 写完整 triones，0x3a0cce4 写 petequips。完整加载为 **0x3a18cb8**（虚表+0x1a60）。

2026-10-12 范围校准：candidate03 原 UI 显示火丸 Lv1、前两槽可点击；缺丹药时提示“当前还没有涅槃丹”，尚未发出 cmd474。这不能证明 Lv1 已具备消耗丹药/超进化资格。`0x3a044e4(pet,index)` 是 0 基槽读取；`0x3a04524` 只把值 0 的槽改成 1，值 1 表示已开启的空槽。静态存在 cmd474 sender 不等于当前面板实际使用它，必须捕获真实选药后的请求再决定接入点。只读探针 `artifacts/zmxol-offline/frida/pet-pill-request-probe.js` 的网络观察限定474，另观察本地暂选/取消函数，只输出有关标量，不记录 full savedata。

cmd474 的最小事务边界已核实：`0x2c03794(manager,Json*)` 唯一直接调用为 `0x2c19a8c`，返回值在 `0x2c19a90..94` 检查；true 后才发 GO_ON（`0x2c19b74`）并清除 bag dirty bit 2（`0x2c19b80`），false 走原错误处理。若自然 UI 确认使用该路径，可以在该函数原生执行后、返回 true 前，验证真实 bag 减少 1 与 pet.triones 对应槽变化，再原子提交两个完整快照；不必改共享 GO_ON。`result` 的各字段有 hasMember 守卫，triones-only 可保留未提供的资质/技能/装备字段，并执行原生属性重算。但目前没有自然474请求，生产分支尚未添加，不能宣称丹药培养已修复。

进一步静态核实：普通培养面板 `0x26e30dc` 的选药事件在 `0x26e3190..98` 校验 0..8 索引。`0x26e3200→0x2c008f0` 读取 pet virtual+0x1800，返回 stage≤3。该分支先 `0x26e3298→0x2c10ee8(manager,index,itemId)` 写 PetMgr+0x420 的临时选择表，再 `0x26e33b0→BagMgr::0x2d2916c` 扣 1。stage>3 则 `0x26e34b4→0x2bfc214(manager,item,pet,index)` 正式本地入槽，再 `0x26e34fc` 扣 1。这两条面板路径没有调用 cmd474 sender。低阶临时选择表不同于序列化的 pet+0x1610 正式 triones，不可将“选中后暂时少1”当作已持久化培养。

candidate05 自然操作已验证低阶分支：主线程从原邮箱领取后，在第一槽选 504100；`r12-pill-close.log:11418` 记录 `native-pet-pill-selected`，slot=0、itemId=504100、accepted=true，未出现 REQUEST_PET_CHANGE_TRIONE。关闭培养后，日志 11439..11445 显示原 REQUEST_SAVE_DATA 提交 4889 字节并 success=1。`r12-pill-close-save.json` 中 Mock mail 900504100 为 committed，bag.item 保留 `{"A2":504100,"A4":1}`，pet4399/dataid210/level1 的 triones 仍为原九个槽值。主线程截图为 `r12-pill-preview-slot.png`。这些证据确认暂选、关闭自动返还、原 SAVE 闭环，不证明正式入槽或属性增长；无需为这一正常流程补响应或伪造474。

后续只有实际流程出现离线阻塞时，才补经原 UI 验证的物品/槽位状态转换，复用原 loader；不要另造加攻加血结果。正式培养的门槛、替换规则及同类型限制尚未全部实测，不能通过直接写 triones/petequips 绕过这些前置条件。

## 必须一起持久化的状态

1. 邮件领取前，保存原请求真实 savedata；Mock mail 本身有独立 ledger，关联本地 rid、mail ID、附件完整 JSON、pending/committed receipt。
2. 领取后验证原生 bag 快照和实际入包数量/装备实例，然后把 bag、point 与 receipt 一起原子提交，完成后再通知 UI。重复/已提交请求必须阻止再次进入原发奖 handler，不能回带 reward 的同一成功响应。
3. 正式使用丹药或八卦时，同一次事务保存实际 bag 与完整 pet，而非只保存请求前快照。对于实际使用 cmd474/475 的分支，0x2c19b78..0x2c19b80 会清 bag dirty bit2，等待之后普通 SAVE 可能漏掉此次背包变化。candidate05 的低阶暂选关闭流程已自动返还并原 SAVE，不走该网络回调，不能强加正式入槽事务。
4. PetManager singleton 0x2c1348c，完整 serializer 0x2c1ab40；输出 petinfo[]/bagsize/maxglobalpetid。ROLE loader 0x2c1ae44 会清旧宠物并恢复完整列表。它会更新 maxglobalpetid 缓存，宜复用同次原保存输出，或在明确边界使用单宠物 serializer，不能把 full builder 当纯读工具重复调用。
5. 原 bag serializer 0x2d4053c 可用于回调后完整快照；遵守已有 x8 返回 ABI。current point 必须保真，不给零、不赠点券。邮件 ledger 不投影为 ROLE_DATA 奖励指令，也不能把领取日志在登录时重新发奖。

## 最小验收顺序与未完成项

| 阶段 | 具体动作 | 通过条件 |
| --- | --- | --- |
| A：列表 | 隔离备份当前存档，点击原邮箱，捕获 cmd552 分类；生成一封明确 Mock 的单丹药测试信 | 列表/标题/附件/过期时间可读；无额外在线阻塞；尚不称领取通过。 |
| B：单件领取 | 原 UI 领取 504100×1；保存自然请求、回包、原入包后快照 | 背包恰好多 1；领取 receipt 已提交；重复点击/重放不加奖；冷启邮件状态与背包一致。 |
| C1：低阶暂选 | Lv1 原 UI 选择已有开放槽，正常关闭培养 | 已验证 slot0 选中；关闭后原返还并 SAVE，bag仍1、正式triones不变。无需新增474。 |
| C2：正式培养 | 满足原门槛后，通过原 UI 捕获实际本地调用或请求，按命中路径接入 | 原生计算生效、真实消耗与正式triones一致、冷启保持；不能假定必经474。未执行。 |
| D：八卦发放 | 原工厂生成并固化 504200..504207，各 1 个，独立 Mock 信 | 工厂/序列化往返属性稳定，A5 唯一，原入包成功；逐个冷启保持。 |
| E：装备与套装 | 达到原超进化和装备条件后走原装备/卸下/替换 UI | 背包与 petequips 间同一 A5 只存在一处；原属性重算，八件齐全触发原套装；卸下恢复，冷启不丢失。 |

当前 A 列表、B 的原 UI 领取/真实入包/receipt 提交，以及 C1 暂选关闭返还/SAVE 已由 candidate05 实机验证；B 的冷启及重复领取验收待主线程完成。C2、D、E 未执行，不能据此称“丹药与八卦已修复”。后续须补正式培养的实际门槛/调用、type27 实例 ID 分配及资源闭包。若为缩短高级系统验收另用具备条件的 Mock 宠物，必须另存隔离测试档并标明来源，不能污染当前自然火丸的成长结论。

调查与出战补丁均未引入数据库或 API 变化。静态反汇编、配置回读、出战专项 pytest 和文档 diff 检查已完成；本文作者未操作 ADB 或执行游戏验收。
