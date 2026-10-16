# 15.7.2 历史内容档案与离线可行性

盘点日期：2026-10-12。依据两份原 APK、512 个解码表、原生类型/协议、完整资源引用和 r11 包；没有使用网络攻略或其他版本传闻。这一轮只建档，没有批量开放活动。

**调查 34 个内容单元：30 个原下载分类 + 4 类活动模板/限时/残留线索。** 下载分类包含灵根、妖天灵域、荒古铸炼等成长系统，不能全部称为已经关闭的“历史活动”。实际开放日期、15.7.2 服务端轮次和奖励配置均按证据保留 UNKNOWN。

## A/B/C/D 结论

| 类别 | 本轮数量 | 标准及结论 |
| --- | --- | --- |
| A | 0 | 必须同时确认代码、资源、配置及玩法逻辑完整；本轮没有项目达到四项门槛 |
| B | 0 | 需确认大部分实际依赖资源和客户端规则，主要缺少部分服务端逻辑；只有表/CCBI/图标不够 |
| C | 34 | 有本地部分资源、配置、类型或协议线索，完整依赖/逻辑/规则未闭合 |
| D | 0 | 本轮不使用外部资料，故没有仅靠外部资料建立的条目；不代表从未存在其他历史活动 |

三界仙厨是**优先补证的 B 候选，当前仍计 C**：包内有 61 个该路径族文件，24 个食谱、50 种材料、28 个关卡掉落配置及厨房/KPI模型。但完整厨房流程、初始活动模型、所有必需资源和服务端奖励语义尚未核定。酿酒、钓鱼、天火庆典虽然保留大量 CCBI/配置，具体图片依赖已有缺口，不能升 A/B。

## 档案目录

“r11/旧包文件数”只统计原 update_resource 声明的路径族，不包括分散在公共界面等位置的资产；零不等于没有代码、CCBI或协议。每个配置键、前缀、三包逐文件清单、字节数见[资源覆盖索引](../artifacts/zmxol-offline/inventory-2026-10-12/update-resource-coverage.json)；可机读档案见[historical-catalog.json](../artifacts/zmxol-offline/inventory-2026-10-12/historical-catalog.json)。

| ID | 内容/原分类ID | 类别 | 原版证据 | r11/旧包声明目录文件数 | 缺项及限制 |
| --- | --- | --- | --- | --- | --- |
| H01 | 仙王之王 / 7566001 | C | update_resource_category[7566001]；update_resource[7563000].path、update_resource[7563001].path、update_resource[7563002].path、update_resource[7563003].path；YJFairyKingWeaponCell@文件偏移0x51a17c0（类型名，非处理函数） | 0 / 0 | 仙王之王主UI/动画全空，清单、匹配和结算未恢复 |
| H02 | 重走西行路 / 7566002 | C | west_journey_level_config[7450000]、west_journey_map_mode_config[7440000]；update_resource_category[7566002]；update_resource[7563004].path；YJWestJourneyModeConfigData@文件偏移0x5218220（类型名，非处理函数） | 0 / 0 | 跑酷参数在，主UI全空；REQUEST_WEST_JOURNEY_ENTER_GAME |
| H03 | 中秋 / 7566003 | C | update_resource_category[7566003]；update_resource[7563005].path；YJMidAutumnResultLayer@文件偏移0x51d6d00（类型名，非处理函数） | 0 / 0 | 游戏/商店协议在；中秋地图、玩法配置和主UI未闭合 |
| H04 | 神秘残卷 / 7566004 | C | mystical_painting_npc_chat[7513101]；update_resource_category[7566004]；update_resource[7563006].path；YJMysticalPaintingMissionLayer@文件偏移0x51afca0（类型名，非处理函数） | 0 / 0 | 70条NPC文本与rule71000131；主UI、修卷概率及任务回包缺 |
| H05 | 器坊新研究 / 7566005 | C | insect_collect_book[7521549]；update_resource_category[7566005]；update_resource[7563007].path；YJInsectInstituteMissionLayer@文件偏移0x51f1ab0（类型名，非处理函数） | 0 / 0 | 35图鉴及rule71000148/71000150；主UI缺，捕虫/交换/领奖协议未本地化 |
| H06 | 七夕 / 7566006 | C | update_resource_category[7566006]；update_resource[7563008].path；YJValentineActivityDyeingHouseLayer@文件偏移0x51d5800（类型名，非处理函数） | 0 / 0 | 活动/染坊/任务类型在；UI缺，轮次、交换规则UNKNOWN |
| H07 | 时来运转 / 7566007 | C | update_resource_category[7566007]；update_resource[7563010].path；YJGoodFortuneBoard@文件偏移0x51f2b40（类型名，非处理函数） | 0 / 0 | 类别名时来运转，路径说明共济鸿福；按表保留名称差异，主UI空 |
| H08 | 势力战 / 7566008 | C | power_war_level[7080001]；update_resource_category[7566008]；update_resource[7563011].path；YJTurfWarSettleCell@文件偏移0x51bf6b0（类型名，非处理函数） | 2 / 104 | 旧包104文件、新包2；多人竞争和结算服务缺 |
| H09 | 永劫炼狱 / 7566009 | C | purgatory_level[7915000]、purgatory_card[7913001]、purgatory_score[7911000]；update_resource_category[7566009]；update_resource[7563015].path；YJEndlessHellRankLayer@文件偏移0x5189790（类型名，非处理函数） | 0 / 0 | 开日、卡组、分数在，主UI缺；REQUEST_ENDLESS_HELL_DISASTER_ENTER |
| H10 | 三界仙厨 / 7566010 | C | cooking_food[7564000]、cooking_material[7567000]、cooking_level_drop[7568000]；update_resource_category[7566010]；update_resource[7563017].path；YJFairychefMaterialClueAlertLayer@文件偏移0x51b1700（类型名，非处理函数） | 61 / 0 | B候选：61文件/24食谱/50材料/28掉落表；完整厨房/绩效/初始状态仍未核实 |
| H11 | 地渊攻坚战 / 7566011 | C | abyss_challenge_level[7916011]、abyss_challenge_level_rule[7918001]、abyssal_battle_level_buff_config[7917111]；update_resource_category[7566011]；update_resource[7563018].path；YJAbyssalBattleCreateLevelData@文件偏移0x5218360（类型名，非处理函数） | 0 / 0 | 难度、机制、Buff在，主UI图集缺 |
| H12 | 月光宝盒 / 7566012 | C | update_resource_category[7566012]；update_resource[7563021].path、update_resource[7563022].path；MoonlightBoxMainUIController@文件偏移0x5353180（类型名，非处理函数） | 0 / 0 | CCBI和类型在；主图集/动画缺；奖励池UNKNOWN |
| H13 | 欢乐庆典 / 7566013 | C | update_resource_category[7566013]；update_resource[7563037].path；MerryFestivalsShopDataSource@文件偏移0x52292c0（类型名，非处理函数） | 2 / 0 | 部分图集和5个CCBI；活动日程/排行/领奖缺 |
| H14 | 禁忌研究 / 7566014 | C | update_resource_category[7566014]；update_resource[7563038].path；ForbiddenBeastShopDataSource@文件偏移0x52292a0（类型名，非处理函数） | 0 / 0 | 5个CCBI与任务类型；主UI空，研究/掉落逻辑UNKNOWN |
| H15 | 十年磨一剑 / 7566015 | C | update_resource_category[7566015]；update_resource[7563039].path；WhetsSwordBattleInfo@文件偏移0x52292e0（类型名，非处理函数） | 0 / 0 | 6个CCBI及战斗信息类型；主UI缺，装备奖励状态未读 |
| H16 | 御剑西游 / 7566016 | C | holding_sword_config[8184000]、holding_sword_enemy[8183894]、holding_sword_parameter[8249001]；update_resource_category[7566016]；update_resource[7563057].path；HoldingSwordWestboundWarWoundPopupController@文件偏移0x52db560（类型名，非处理函数） | 0 / 0 | rule71000269含单局增益；主UI缺，110敌配置未动态验 |
| H17 | 混沌军团 / 7566017 | C | chaos_force_job[8183600]；update_resource_category[7566017]；update_resource[7563068].path；ChaosLegionChatBoardLayer@文件偏移0x5344130（类型名，非处理函数） | 0 / 0 | rule71000275含五周/匹配/镇守；UI缺，多人语义重 |
| H18 | 圣邪青龙 / 7566018 | C | update_resource_category[7566018]；update_resource[7563069].path；YJCampaignQinglongStoreListCell@文件偏移0x51e4060（类型名，非处理函数） | 0 / 0 | 4个CCBI和活动类型；主UI、完整成长/奖励规则缺 |
| H19 | 钓鱼 / 7566019 | C | fish[8185500]、fish_illustrated[8185596]、fishing_rod[8185600]；update_resource_category[7566019]；update_resource[7563084].path；SummerFishingDisplaceSucessPopupController@文件偏移0x5368b00（类型名，非处理函数） | 2 / 0 | rule71000279；23个具名路径缺16，未达B级资产门槛 |
| H20 | 龙心旧梦 / 7566020 | C | update_resource_category[7566020]；update_resource[7563088].path；LongXinOldDreamHomeUIController@文件偏移0x5326660（类型名，非处理函数） | 0 / 0 | 18个CCBI和挑战排行类型；主图集缺 |
| H21 | 妖天灵域 / 7566021 | C | fairy_domain_level[8280101]、fairy_domain_grade[8290600]、fairy_domain_mirror_drop[8261000]；update_resource_category[7566021]；update_resource[7563092].path、update_resource[7563103].path、update_resource[7563104].path、update_resource[7563128].path；DemonSkySpiritRealmGroundSelectPopupController@文件偏移0x52e0a90（类型名，非处理函数） | 212 / 0 | 常驻成长候选；部分地图动画在，demon_spirit骨骼空 |
| H22 | 铁粉盲盒 / 7566022 | C | blind_box_room[8262500]；update_resource_category[7566022]；update_resource[7563093].path、update_resource[7563094].path；IronPowderBlindBoxGiftBoxUIController@文件偏移0x5338620（类型名，非处理函数） | 11 / 0 | 11个CCBI在，14个具名路径缺12；盲盒池/社交回包缺 |
| H23 | 灵根 / 7566023 | C | spiritual_root[8320111]、spiritual_body[8330101]、spiritual_stone[8340000]；update_resource_category[7566023]；update_resource[7563095].path；YJAllKarmaRootInfo@文件偏移0x51d2ee0（类型名，非处理函数） | 0 / 0 | 常驻成长候选；29个具名路径缺20，不能当已还原活动 |
| H24 | 梵天塔 / 7566024 | C | tower_of_brahma_level[10101111]、tower_of_brahma_relic_stage[10101000]、tower_of_brahma_law[11001000]；update_resource_category[7566024]；update_resource[7563102].path；YJBrahmaTowerLevelData@文件偏移0x5218a50（类型名，非处理函数） | 6 / 0 | 2480层级/248遗迹配置；UI部分缺，次数和掉落服务状态缺 |
| H25 | 荒古万界 / 7566025 | C | hyperborea_task_chain[6870001]、ancient_leviathan_suppress[8262560]；update_resource_category[7566025]；update_resource[7563106].path、update_resource[7563107].path、update_resource[7563108].path、update_resource[7563109].path、update_resource[7563130].path；AncientTimeBeaconCellUIController@文件偏移0x52c1680（类型名，非处理函数） | 7 / 0 | 前置/穿梭/主背景动画缺；常驻和周期边界UNKNOWN |
| H26 | 荒古铸炼 / 7566026 | C | ancient_equip_forge[8560001]、ancient_equip_refining_spectra[8563001]；update_resource_category[7566026]；update_resource[7563114].path；AncientEquipmentQuenchMeaningInfoPopupController@文件偏移0x53793d0（类型名，非处理函数） | 0 / 0 | 成长系统，非已证历史活动；主图集空，43个CCBI保留 |
| H27 | 侠影醉龙门 / 7566027 | C | wine[8262400]、wine_map_explore[8262510]、wine_reward[8566500]；update_resource_category[7566027]；update_resource[7563117].path；MakeWineBodegaPopupController@文件偏移0x529b790（类型名，非处理函数） | 2 / 0 | rule71000319三步骤；75路径缺60；社交共饮不可直接当单人原版 |
| H28 | 梦入武林 / 7566028 | C | dream_wulin_escort[8566600]、dream_wulin_wanderer_bond[8566701]、dream_wulin_wanderer_reward[8566200]；update_resource_category[7566028]；update_resource[7563120].path；YJDreamMartialRangerBondData@文件偏移0x5218db0（类型名，非处理函数） | 0 / 0 | 50个CCBI，44路径缺33；赠礼/护送/好感状态未恢复 |
| H29 | 天火庆典 / 7566029 | C | skyfire_celebration_store_level[8566600]、skyfire_celebration_crafted_item[8566800]、skyfire_celebration_gala[8567000]；update_resource_category[7566029]；update_resource[7563123].path；YJSkyFireStoreLevelData@文件偏移0x5218e60（类型名，非处理函数） | 10 / 0 | rule71000340规定7/14天；24路径缺18；摆摊计时、收益和排行缺 |
| H30 | 缤纷庆典 / 7566030 | C | update_resource_category[7566030]；update_resource[7563131].path；ShenQueDrawLotsBookCellUIController@文件偏移0x5297610（类型名，非处理函数） | 0 / 0 | rule71000345问签规则；8个CCBI、主图集空，权重和奖品清单UNKNOWN |
| H31 | 自定义活动1–4 / 独立线索 | C | update_resource[7563019/7563081/7563100/7563129]；REQUEST_CAMPAIGN_CUSTOM_HOME | UNKNOWN：非独立声明目录 | 四模板目录全空，实际活动主题和奖品依赖服务端内容 |
| H32 | 龙门福地等限时副本 / 独立线索 | C | level[100001]、module_open_guide[909205]；level[100045].is_time_limit_open；module_open_guide[909205] | UNKNOWN：非独立声明目录 | 12条level标限时；开放次数/资源/奖励闭包未验证 |
| H33 | 节庆技能与历史道具残留 / 独立线索 | C | festival_skill[6400041]；festival_skill[6400041]等5条；item/loot索引 | UNKNOWN：非独立声明目录 | 技能、道具或图标名称只能建档，不能证明整个节日玩法在 |
| H34 | 冰窟波次/轮次奖励挑战 / 独立线索 | C | ghost_cave_ice_round_rewards[7512001]、ghost_cave_ice_wave_rewards[7511000]；16轮次/192波次配置 | UNKNOWN：非独立声明目录 | 入口及完整结算未恢复；是否历史/周期活动UNKNOWN |

## 精确资源缺口

扫描不是只找 UI 文字：读取 CCBI 二进制内完整文件路径，解析已存在 plist 的纹理引用、Spine atlas 页和 TMX 图片，再比对两个原包及 r11。全部 810 个 CCBI 抽出 702 个唯一具名路径，其中 501 个在 r11 和旧包同路径都没有。以下缺项均能追踪到引用它的 CCBI：

| 内容 | CCBI 具名路径总数 / 缺失 | 缺失路径示例（均位于 assets/images/hd/） |
| --- | --- | --- |
| 酿酒 | 75 / 60 | interface/layers/layer_make_wine/layer_make_wine_bodega/layer_make_wine_bodega.plist |
| 钓鱼 | 23 / 16 | interface/layers/layer_summer_fishing/home/home.plist |
| 天火庆典 | 24 / 18 | interface/layers/layer_skyfire_celebration/common/common.plist |
| 梦入武林 | 44 / 33 | interface/layers/layer_dream_martial/role_info/role_info.plist |
| 梵天塔 | 15 / 7 | interface/layers/layer_brahma_tower/battle_pass/battle_pass.plist |
| 荒古万界 | 28 / 20 | interface/layers/layer_ancient_time/area_info/area_info.plist |
| 灵根 | 29 / 20 | interface/layers/layer_all_karma_root/layer_all_karma_root_common/layer_all_karma_root_common.plist |
| 器灵 | 15 / 10 | interface/layers/layer_fairy_equip_spirit_board/spirit_level_entrance/spirit_level_entrance.plist |

对应 CCBI 文件、字面量和三包存在标记见[完整引用证据](../artifacts/zmxol-offline/inventory-2026-10-12/ccbi-resource-references.json)。这里只识别具名完整路径，不把 sprite frame 名当独立 PNG，也没有穷尽动态拼接路径。可能的 loader 别名/替代图集需另有证据；不能用猜测抹掉缺项，也不能仅据缺项宣称运行必然崩溃。

12 条明确标限时的 level：100045 龙门福地、100047 须弥山、100048 虚空之境、100050 上古遗迹、100057 九龙岛、100058 碣石山、100059 碧游宫、100066 玄风洞、100067 五庄观、100068 暗影魔窟、100079 血色魔狱、100116 蓬莱。各条 is_time_limit_open=1 是原配置事实；限时不等于已经删除，不推出具体历史开放日期。

## 独立收藏入口的可行路径

先建立只读档案入口，以“版本指纹 + category_id + 原配置键”为索引，展示原名称、说明、已知资源及缺项。只读档案不发奖励、不改变原角色状态，也不计为玩法恢复。

当某项达到 A/B 条件后，再追踪原场景/控制器初始化路径，注入已经解析的本地活动初始模型。活动轮次、进度及领奖记录必须有独立命名空间，避免覆盖主线存档或误用原服务器过期状态。当前桥接只支持有限模块，先明确 loader/serializer 和状态转换，再扩白名单；无需现在搭大型框架或批量放开所有活动。

优先保留原本地物品表、配方、消耗和客户端物品工厂。只有服务器才知道的数量、概率、排行榜、限额和周期奖励保持 UNKNOWN。若后来选择兼容规则，须明确标记为“离线重建”；目前700002/700003数量1、等概率的用户取舍不自动成为所有活动的规则，也不能计入原版还原度。

匹配、玩家交换、联盟竞争、好友共饮等不能用假玩家/假排名冒充完整恢复。A阶段可研究抽离有完整本地逻辑的单人部分，但必须说明与原多人语义的差别；真实服务器接入留B阶段。

## 按依赖排序的补证队列

1. **先完成当前主线 r12**：700003普通结算→制作书→原配方生成装备→使用/冷启，并执行真实强退和重复奖励门禁；历史入口不破坏已有 r11 基线。
2. **三界仙厨**：沿 YJFairychefKitchenLayer/Manager、REQUEST_FAIRYCHEF_COOK_FOOD 与 KPI 请求查初始状态、配方选择、材料消耗、产物保存，核完整资源后才调整 C→B。
3. **有规则但缺资产的内容**：御剑西游、神秘残卷、酿酒、钓鱼、天火庆典。逐条核 CCBI→plist→纹理、原模型和奖励；两个 APK 中没有的资源列为阻塞，不生成素材冒充原版。
4. **多人/大世界依赖强的内容**：势力战、混沌军团、仙王之王、交易和排名，先分离可复用单人战斗与服务端状态。
5. **模板与道具残留**：自定义活动、节庆技能及日期不明内容只保留档案；新证据出现再改分类，没有“自动补全”为原版玩法的步骤。

## 可复用记录

| 内容 | 类型 | 范围 | 来源/验证 | 更新时间 | 失效或复查条件 |
| --- | --- | --- | --- | --- | --- |
| 下载分类/CCBI/道具数量不等于可玩历史活动数量 | 证据口径 | 两原APK/r11 | update_resource、ZIP及实际依赖引用 | 2026-10-12 | 新资源包、原初始化或运行证据出现 |
| 34调查单元暂C，A/B/D为0 | 当前判断 | 本轮档案 | 代码/资源/配置/逻辑四项门槛 | 2026-10-12 | 原资源、服务响应或完整玩法分支补齐 |
| 缺失路径和未使用地图引用分开记录 | 排查方法 | 资源扫描 | level100910缺8图但图层GID未使用 | 2026-10-12 | 地图/加载器发生变化 |

本轮没有历史活动实玩、ADB操作或真机验证。扫描及文档工具10项pytest、自检和文件校验见[验证记录](../artifacts/zmxol-offline/inventory-2026-10-12/verification.json)。没有修改原APK、历史存档、桥接或QQ数据库/API。
