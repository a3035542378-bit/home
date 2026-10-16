# 15.7.2 V3 调查与质量门禁报告

日期：2026-10-14，Asia/Shanghai。

**结论：工程核查、46个真灵映射/候选评分和觉醒契约调查已完成；真灵最小业务闭环尚未恢复，准出BLOCKED。公共质量门禁发现并修复了FN SDK断网未捕获异常，工作源已完成模拟器外置源码冷启验证，但尚未打入新签名APK。** 不将调查或测试注入视为自然获取成功。

## 完成内容与关键判断

1. 指定四份核心文档、稳定性报告、两原APK、稳定性APK和当前存档实际核查，分支master，保留既有QQ修改。原包指纹及稳定包签名v1/v2/v3重核通过。详情：[基线](zmxol-offline-v3-baseline.md)。
2. 从pet.is_beast/type、born_skill、ai_file、融合target偶数位和材料引用建立46个ID映射；逐成员SHA/长度及atlas全部纹理页检查。当前包仅9043/9044/9045基础组闭合，页数4/4/1；旧包另16组迁移候选，19组合并候选、27组在已证布局未找到。基础组存在不证明动画/技能/音效闭包。详情：[映射](zmxol-offline-true-spirit-resource-map.md)。
3. 按25/25/20/15/15证据覆盖权重评分；9045霓云腾蛇39分、9043/9044各35分，优先补证9045的38条融合配置。完整实例/serializer、唯一ID分配、权威融合随机继承和材料/实例提交点仍缺，所有候选均不能实施完整闭环。详情：[选择](zmxol-offline-true-spirit-selection.md)、[专项分析](zmxol-offline-true-spirit-analysis.md)。
4. 觉醒开槽/充能/点火/嵌石cmd202–205、共同consumer、点火cost处理和result分支补证。正式费用、成功概率及失败资产变化UNKNOWN；技能配置0.1不能用作点火成功率。详情：[契约](zmxol-offline-awakening-contract.md)。
5. 复用现有原工厂、native snapshot和原子save；没有重构资产框架，没有放开未知true_spirit_bag白名单，没有新增空成功响应或扣费逻辑。

## SDK 冷启异常与最小修复

原稳定包在PID2461冷启中于FN SDK线程抛 `SecurityException: Permission denied (missing INTERNET permission?)` 并退出；原崩溃栈见[launcher-crash.txt](../artifacts/zmxol-offline/v3-20261014/launcher-crash.txt)。系统Launcher最终也指向原游戏Activity，不能把这次异常解释成“另一个Launcher入口”；直接启动有成功也有失败，原包间歇问题确实存在。

重新反编译原APK DEX确认：SsjjFNUtility.openUrlOnceWithTimeOut发起HTTP，上层FNHttpWrapper仅处理IOException/SsjjFNException；IOException会转BgpResponse(state=-1,errCode=-2,httpCode=-1)，经SsjjFNException送FNHttpProcessor原失败/NET_ERR回调。空字符串会走成功状态，故不能用空响应替代。

工作源仅在离线SDK方法边界抛固定消息IOException，不发送网络、不记录URL/headers/请求参数、不恢复INTERNET权限。原游戏请求桥、资产、战斗native和保存实现不变。最终源SHA256 **`50bf21c36cf0ac6bce7a30297ec35d9df981c1aeafcfa4d7e012bad6dda8d95c`**；[冻结源码](../artifacts/zmxol-offline/v3-20261014/sdk-fixed-production-frozen.js)。

实施过程首次误用了SsjjFNParameters的包名，Java替身测试没有发现。已按原import和真实DEX原型修正为 `com.ssjj.fnsdk.core.entity.SsjjFNParameters`，新增实际15.7.2 DEX签名检查。旧失败截图sdk-fix-launcher-cold2不能计为最终修复成功。最终生产源码移除sdk-bootstrap-diagnostic，设备实际脚本hash与工作源相同；ready和blocked事件证明实际SDK失败入口生效。

原SDK后台BGP仍会重试，本轮没有修改其重试/退避，也没有证明任意时长不再出现其他启动故障。FN SDK失败路径的Java/DEX证据在v3-20261014目录，真实线程安全和时序以实际冷启为依据。

## 模拟器、存档与人工操作边界

测试设备仍为emulator-5576/专用zmxol_api30 AVD，包名com.zmxyol.union.uc。过程中模拟器曾退出，SDK崩溃与模拟器退出分开记录：后者原因不充分，不能归咎游戏。恢复同一AVD，未清数据；headless运行避免窗口关闭中断。恢复后ADB root、飞行模式1/Wi-Fi0，IPv4/IPv6 OUTPUT重新限制loopback，官方原数据未覆盖。

备份tar354条/权限600/SHA `e6ee12f02fa901722a45775afc955bb23bd2ae6c0f2ecf451fb60fc2d4571af8` 可读；初始11,810字节save SHA `ec8c83c4364f02d49c7599bf1fe5bd56a677f7fae8dad61fddc748030cca637c`。AVD恢复后save仍与初始逐字节一致。

期间用户明确确认手动切换过宠物和背包。按实例对齐核查，仅虬龙棍4413/尾火棍4401的A6穿戴标记及pet4400/4399的tamestate变化，列表顺序随原保存变化；物品身份集合、材料/其他字段、宠物成长/经验/技能、90级、余额、邮件与翻牌收据均保持。没有恢复旧备份覆盖用户新选择。

最终生产源码两次冷启（PID1910、2078，第二次走系统Launcher）均恢复原ROLE_DATA、进入城镇，用户切换后的存档前后**逐字节一致**，SHA **`f7bfd88676e6c32baebc8158a2fb9f821686fa1482b4a670cdc9599c4329d75f`**。当前用户选择火丸4399出战、圣佛邪君4400休息，五只宠物保持；不将此人为切换计为回归或由SDK修复生成的数据。

证据：[首次源码冷启](../artifacts/zmxol-offline/v3-20261014/production-source-cold1.png)、[Launcher冷启](../artifacts/zmxol-offline/v3-20261014/production-source-launcher-cold2.png)、[原桥事件日志](../artifacts/zmxol-offline/v3-20261014/sdk-fixed-production.log)、save-production-cold1/save-production-launcher-cold2及[结构化结果](../artifacts/zmxol-offline/v3-20261014/final-verification.json)。保存文件权限600，不公开分享包含用户状态的备份。

**当前模拟器为外置修改后的生产源码验证环境，APK本体仍为2498df…稳定包；不是新签名APK完整验收。** 旧提取脚本已备份installed-script-before.js，原APK和全部历史包保留。没有手写任何成功状态、guide或真灵对象。

## 自动化回归

| 本轮执行 | 执行数 | 通过 | 失败 | 跳过 | 说明 |
| --- | ---: | ---: | ---: | ---: | --- |
| 开始时完整tools/zmxol | 758 | 758 | 0 | 0 | 29.96s，重核历史数量 |
| 最终完整tools/zmxol | 767 | 767 | 0 | 0 | 28.47s；新增9项=映射7+SDK2 |
| 邮件辅助/诊断 | 40 | 40 | 0 | 0 | 0.84s；24当前助手+16旧validation3冻结诊断；24与全套重复，不能直接相加为807个不同测试 |
| JS语法 | 1次检查 | 通过 | 0 | — | node --check |

最终XML/文本：final-767-regression.xml/txt、frozen-mail-40.xml、final-mail-40.txt，均在v3-20261014。初跑历史16诊断有14通过/2失败，原因是其gen.SOURCE仍指当前源而断言绑定旧7a哈希；通过显式冻结输入选择复核，未改断言或覆盖生产源码。[runner](../artifacts/zmxol-offline/v3-20261014/run_frozen_mail_tests.py)保留输入选择方式，不把旧16项称作当前SDK的动态证明。

新增映射测试是ZIP替身/工具测试，SDK一项Java替身及一项真实DEX原型测试；现有完整回归主要为native/IO契约替身。不是全游戏真实回归。已有火丸捕获、圣佛邪君领取/战斗、邮箱强退/EIO/幂等、灵物教学、翻牌及合成真实证据仅核读，本轮没有逐条重新点击执行。SDK源码冷启、存档和入口状态为本轮真实设备验证。

## 修改文件、数据库与API

- 修改tools/zmxol/offline_bridge.js，新增test_offline_sdk_network.py、true_spirit_inventory.py、test_true_spirit_inventory.py；更新tools/zmxol/README.md。
- 新增V3基线、真灵资源映射、对象选择、觉醒契约及本报告；更新专项分析、功能矩阵、下一系统计划、复活记录和ai-context。
- 新证据、快照、源码冻结、反汇编及测试结果仅写入已忽略artifacts/zmxol-offline/v3-20261014。
- 数据库无迁移、无表变更；API无变化；没有修改QQ项目实现或已有未提交内容。

## 尚未完成与下一步

真灵自然入口、获取、完整实例、培养、属性/合体、实战结算、真灵存档及全部异常/幂等/冷启仍未通过。没有真灵恢复代码，只有调查工具、证据及公共SDK修复；没有新真灵APK。所有候选关键缺口明确列入选择门禁，不能为了完成要求填假对象或概率。

下一步优先9045：确认38条配置中一条合规主辅组合→精读完整目标对象serializer及ID setter→确认权威计算可由本版证据重建→确认扣材/生成/提交/重放/中断事务；达到门禁才写桥接并进行真实原UI获取与培养。觉醒继续追cost来源与result失败资产规则。SDK改动若单独打包，需另做完整签名包启动与原功能验收，本轮不将外置source通过冒充该准出。

实体ARM64手机、物理断电、全内容/其他角色、全资源动态闭包和官方服务端缺失规则未验证。没有扩大到B阶段。
