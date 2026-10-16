V6.1最新：独立材料商城R3（仅三商品，六类PARTIAL），测试赠券200万、五项指定价格独立维护于`offline_shop_prices.json`；7893条仅候选，不能批量视为可售。最终包/设备/909项回归及R1/R2否决原因见[报告](../../docs/zmxol-offline-v61-report.md)与[checkpoint](../../docs/zmxol-codex-checkpoint.md)。不要分发V6.1 R1/R2。

# 造梦西游 OL 离线改造工具

最新V6独立测试构建与实际边界见[交付记录](../../docs/zmxol-offline-v6-report.md)。仅分发`v6-20261015/15.7.2-offline-v6-test-r4.apk`；R3否决。R4非root ADB断网跑通700002五星、领奖、回村及冷启，完整工具883通过；不是全内容完成。新`build_playable_apk.py`以SHA锁定底包、内置初档和原资源，构建时定点替换两条联网提示；`playable_bridge.py/js`不读取外置DEBUG触发文件。现有档不覆盖，私钥仅用于既有独立签名工具，不进入Git。

2026-10-14 V3增量：[工程基线](../../docs/zmxol-offline-v3-baseline.md)、[真灵资源映射](../../docs/zmxol-offline-true-spirit-resource-map.md)、[选择门禁](../../docs/zmxol-offline-true-spirit-selection.md)、[觉醒契约](../../docs/zmxol-offline-awakening-contract.md)及[验收报告](../../docs/zmxol-offline-v3-report.md)。真灵仍未恢复；下文r11数字属于历史。工作源新增SDK断网IOException失败边界，外置源码测试与旧签名APK区别见报告。

只读真灵映射使用现有Python环境，不改APK或存档，输出必须为新文件：

```sh
artifacts/zmxol-offline/analysis-venv/bin/python tools/zmxol/true_spirit_inventory.py \
  artifacts/zmxol-offline/15.7.2/decoded/database \
  '/Users/baize/Downloads/造梦西游OL.apk.1' \
  '/Users/baize/Downloads/造梦西游OL.apk (1).1' \
  artifacts/zmxol-offline/squad-build/15.7.2-mail-stability-signed.apk \
  /private/tmp/true-spirit-map.json
```

映射只确认基础模型和atlas全部纹理页，旧包兼容、动画/子弹/音效动态引用、逐ID协议和完整serializer仍需原生契约核验。

这些是独立的分析与改包工具。r11 已通过火丸捕捉、商城/被动技能教学的保存和冷启动恢复，最新 4434 字节进度重开后完全一致。此前已验证天宫道 1 五星、翻牌、回村和葫芦合成，当前仍是部分功能实验版。构建器默认的 `EXPERIMENTAL_NOT_PLAYABLE` 表示仅构建不能证明可玩；实际验收与限制见 [`../../docs/zmxol-offline-revival.md`](../../docs/zmxol-offline-revival.md)。不修改 QQ 平台数据库或 API。

可用测试包：[`15.7.2-gadget-r11.apk`](../../artifacts/zmxol-offline/squad-build/15.7.2-gadget-r11.apk)，**2,083,968,652 字节**，SHA-256：`b8a6366e003d7541fc1bb29dd62da75af89335d0c1cb96a432797a8803d1d7a6`。仅支持 ARM64；全游戏与真机兼容尚未完成验收。

## 环境与检查

Python 3.12 以上；配置解码依赖 `cryptography`，测试依赖 `pytest`。Java 工具复用已安装的 JADX 1.5.5 中的 apksig 与 dexlib2，使用本机 OpenJDK 编译。当前任务的独立环境位于已忽略的 `artifacts/zmxol-offline/`。

```sh
artifacts/zmxol-offline/analysis-venv/bin/python -m pytest tools/zmxol -q
```

部分测试读取用户提供的真实 APK 和本机 Java 工具；缺少这些输入时明确跳过，不能把跳过当作通过。

## 启动测试包

`apk_patch.py` 只接受记录中 SHA-256 对应的 15.7.2 原包，拒绝覆盖已有输出。默认替换两个渠道初始化方法。`--ace-dex` 用于保护层初始化实验；本轮原生启动实验不使用此选项。

```sh
artifacts/zmxol-offline/analysis-venv/bin/python tools/zmxol/apk_patch.py \
  '/Users/baize/Downloads/造梦西游OL.apk (1).1' \
  artifacts/zmxol-offline/15.7.2/new-startup-unsigned.apk
```

`native_restore.py` 核对原始 ARM64 `libgame.so` 与运行时快照指纹，恢复代码、只读数据、399 项导入重定位及 4987 槽位初始化表，并将文件偏移 `0x67a2568`、`0x67a2634` 的 `080100d0` 改为 `20000014`，分别转发资源读写到原 `fread`、`fwrite` 跳板。输出仍标记 `EXPERIMENTAL_NOT_PLAYABLE`。

```sh
mkdir -p artifacts/zmxol-offline/squad-build
artifacts/zmxol-offline/analysis-venv/bin/python tools/zmxol/native_restore.py \
  /private/tmp/zmxol-revival-newer/lib/arm64-v8a/libgame.so \
  artifacts/zmxol-offline/15.7.2/game-runtime-code.bin \
  artifacts/zmxol-offline/squad-build/libgame.so
```

`--game-library` 与 `--tprt-library` 必须成对指定，仅接受以下已核对 SHA-256，不接受任意原生库：

| ARM64 输入 | SHA-256 | 变更 |
| --- | --- | --- |
| `libgame.so` | `91a8b745b51a2e4b7743a94d5fe7f1e6e1ec50c1ed6149c64d2b5b2cf5b9ddb0` | 上述恢复及 `fread`、`fwrite` 转发补丁 |
| `libtprt.so` | `18457ba0f0af412857a4047c029025bb17dbf2e93f6e0c1516bf9f75bed0b97f` | 原库文件偏移 `0x5bb90` 的 8 字节改为 `00008052c0035fd6`，初始化函数返回 0 |

```sh
artifacts/zmxol-offline/analysis-venv/bin/python tools/zmxol/apk_patch.py \
  '/Users/baize/Downloads/造梦西游OL.apk (1).1' \
  artifacts/zmxol-offline/squad-build/15.7.2-native-startup-unsigned.apk \
  --game-library artifacts/zmxol-offline/squad-build/libgame.so \
  --tprt-library artifacts/zmxol-offline/15.7.2/native-experiment/libtprt.so
```

生成报告记录原包指纹、DEX 修改项、两个原生库的输入与输出指纹及 ZIP CRC 结果。普通启动模式只替换 `lib/arm64-v8a/` 下这两项，ARM32 库保留原样，尚未验证 ARM32。工具校验通过不代表更新、角色、关卡或存档可以离线运行。

## Gadget 自启动实验

`--gadget-library` 与 `--offline-script` 必须成对使用，同时指定上述两个原生库，不能与 `--ace-dex` 混用。Gadget 仅接受 [Frida 16.7.19 官方 ARM64 release](https://github.com/frida/frida/releases/tag/16.7.19) 解压后的二进制，SHA-256 固定为 `61be4bbeae285bb19164dc9eebee58669f6ad2ab4b4d64422ea0a779731b0898`。本地记录包含下载来源及压缩文件指纹；官方资源未另提供独立签名认证。

以下命令使用当前工作区的 [`offline_bridge.js`](offline_bridge.js)，工具不会生成业务脚本。r11 内置脚本 SHA-256 为 `aad6de97caa4cbd3a19db48c8b1f795e929d2d34b7f52a3fc072e85927f5a8fc`，安装后未替换脚本并完成下述实际验收。脚本只使用 loopback 服务地址，不等待电脑端 Frida 回复或依赖 `adb reverse`。离线桥接包使用 `--legacy-apk` 补齐角色和已列入支持范围的关卡资源；只做启动诊断时可以省略该选项。

```sh
artifacts/zmxol-offline/analysis-venv/bin/python tools/zmxol/apk_patch.py \
  '/Users/baize/Downloads/造梦西游OL.apk (1).1' \
  artifacts/zmxol-offline/squad-build/15.7.2-gadget-unsigned.apk \
  --game-library artifacts/zmxol-offline/squad-build/libgame.so \
  --tprt-library artifacts/zmxol-offline/15.7.2/native-experiment/libtprt.so \
  --gadget-library artifacts/zmxol-offline/squad-build/frida-gadget-16.7.19-android-arm64.so \
  --offline-script tools/zmxol/offline_bridge.js \
  --legacy-apk '/Users/baize/Downloads/造梦西游OL.apk.1'
```

[`PatchGadget.java`](PatchGadget.java) 使用 dexlib2，在 `classes.dex` 的 `AceApplication.<clinit>` 首部加入 `System.loadLibrary("gadget")`，保留原 `tprt`、`tersafe2` 和 `memoryLoaders` 初始化序列及类数量。Python 工具通过 Java source-file 模式调用它，当前依赖路径为 `/opt/homebrew/opt/openjdk/bin/java` 和 `/opt/homebrew/opt/jadx/libexec/lib/jadx-1.5.5-all.jar`。SDK 的两个既有方法仍由原补丁处理。

新增条目固定如下；三项均使用 ZIP DEFLATED，配置和脚本名称符合 Android native 目录提取规则。配置固定为 Gadget `script` 交互、`qjs` runtime、`on_change: ignore`，脚本相对路径为 `liboffline.script.so`，不启动 Gadget 控制端监听。[Gadget 官方文档](https://frida.re/docs/gadget/)

| APK 条目 | 内容 |
| --- | --- |
| `lib/arm64-v8a/libgadget.so` | 固定版本的 ARM64 ELF |
| `lib/arm64-v8a/libgadget.config.so` | UTF-8 JSON 配置 |
| `lib/arm64-v8a/liboffline.script.so` | 输入脚本原字节，要求非空 UTF-8 且无 NUL |

报告记录三个新增条目的 SHA-256、Gadget 版本和真实 DEX 注入校验结果。Gadget 模式排除所有 `lib/<非 arm64-v8a>/` 条目，报告列出排除的 ABI 和条目数量；普通启动模式不执行此过滤。重复条目、已有 Gadget 条目、异常 ZIP 路径、覆盖已有输出或报告、悬空输出链接均被拒绝；构建期间出现同名输出也不会覆盖。未签名 ZIP 不保留原 v1/v2/v3 签名，仍须后续单独签名。

Gadget 模式还通过 [`offline_manifest.py`](offline_manifest.py) 删除 `AndroidManifest.xml` 中全部 `android.permission.INTERNET` 声明，包括重复的 `uses-permission`、`uses-permission-sdk-23` 和 `uses-permission-sdk-m`。它只删除对应二进制 AXML 节点并更新总长度，string pool、其他权限及其余节点原字节保留；缺失 Manifest、畸形结构或无法判定的权限名称会中止构建。报告的 `manifest.removed_permissions` 列出删除的元素和权限名，`manifest.removed_permission_count` 记录数量；无该权限时为 0，普通模式保留 Manifest 和原报告格式。移除权限也会阻止应用的 loopback 网络连接，离线脚本必须在本地完成响应处理，不能依赖真实 HTTP 连接成功。

可选 `--legacy-apk` 仅用于 Gadget 模式，调用 [`legacy_resources.py`](legacy_resources.py) 的 `load_legacy_game_resources`，从固定 SHA-256 为 `ecff6494a962e066812434497282adb614c0163cb7be856c1f64be36861e3d6a` 的 11.6.0 原包恢复角色 1、5、怪物 300/301/302/303/304/305/322/323/324、火丸 210 和悟空的 36 组原子弹资源。角色的骨骼、atlas 及全部纹理写入 `assets/images/hd/skeleton/role/1/` 与 `role/5/`；怪物的 JSON、atlas、PNG 写入 `assets/images/hd/skeleton/enemy/`；火丸同类三文件写入 `assets/images/hd/skeleton/pet/`。悟空子弹的 36 份 plist 与 36 份引用的 `.pvr.ccz` 保持原 `assets/images/hd/roles/role_1/bullet/` 路径。另外保留原路径复制 `assets/images/hd/levels/level_static_bg/level_static_1_bg.png` 与 `level_static_2_bg.png`，分别对应天宫道和蟠桃园。共 **315 文件、14,221,007 字节**，包含 217 页骨骼纹理、36 张子弹纹理和两张背景，全部保留原字节，使用 ZIP DEFLATED。火丸两组子弹原新包已有，不重复复制。1112 在两个原包中没有对应文件，本工具不生成替代资源。

helper 核对每份子弹 plist 的 `textureFileName` 与 `realTextureFileName`，只接受已验证的固定同目录纹理名称；异常路径、未知名称、字段冲突、缺失或重复纹理均拒绝。构建遇到已有同名条目、重复项或目录冲突也会拒绝，不覆盖新版资源。`legacy_resources` 报告记录旧包路径、版本、指纹、角色/怪物/宠物/子弹/背景分项与每个文件的来源路径、目标路径、长度、SHA-256。`texture_page_count` 为骨骼 atlas 的 217 页，`pet_ids` 为 `[210]`，`bullet_texture_count` 为新增 36 张子弹纹理，`bullets` 列出原 plist→纹理依赖。新增资源列入 `added_entries`，连同 Gadget 三项共 **318 项**。未指定时不加载旧包，也不增加此报告字段。

此实验包仅支持 ARM64，不提供 ARM32 版本。专用 AOSP API 30 模拟器先前已验证悟空建角、Gadget 自启动、自然入关（ENTER 响应 `state=0`）、九重天 Boss 五星、引导翻牌及尾火棍 +1。r10 使用已有角色继续，实际通过：自有角色 `ROLE_INFO_2` 解锁称号引导 → 天宫道 1（700002）75 秒五星 → 普通抽牌获得檀木 502001 × 1，背包从 1 增至 2 → 回村 → 原引导合成宣花葫芦 500001 → 自然完整保存 → 强制退出后重开恢复。

r11 正式安装后未替换脚本、无 host Frida 服务，已消除蟠桃园教学掉宠时的 `ERROR_ANI_2` 和主动退出：原生葫芦捕获火丸 210，教学自动回村，完成宠物面板及出战操作后自然完整 SAVE。冷启前后存档均为 **4451 字节**，逐字节相同，SHA-256：`9ea0e2d7d1146c136b3e7ec5a70f303c450d0e9b8011e994e202105a56458dbc`。保留 Lv7、56 EXP、2145 灵魂、尾火棍 +1、宣花葫芦，并新增火丸 `petid=4399`、`tamestate=1` 和捕宠引导完成记录。证据见 [`r11-runtime-verification.json`](../../artifacts/zmxol-offline/15.7.2/r11-runtime-verification.json)，此前天宫道流程见 [`r10-runtime-verification.json`](../../artifacts/zmxol-offline/15.7.2/r10-runtime-verification.json)。`REQUEST_PET_SET_TAMESTATE` 仍返回失败，本次状态由客户端本地修改后随完整 SAVE 持久化，不能据此认定该接口恢复。

此后原商城教学赠送 198 虚拟点券，购买并使用一瓶小灵魂药水，灵魂增加 20000；随后被动教学花费 5000 灵魂学习热血（skill 200、grade 1），生命值 455→655。最新自然 SAVE 为 **4434 字节**，SHA-256：`4fb975c7b4a1a97c66df3facbe0471a654bb5941293a5fccedd7f74c6120a63a`，含 17145 灵魂、点券 0 和出战火丸。模拟器进程曾退出 137，原因未证实；重启同一 AVD、未清除数据并禁外网后，最终冷启 ROLE_DATA 成功，前后存档逐字节相同，停在讨伐任务板教学。最终日志/截图与上述首次 4451 字节宠物冷启证据均保留；这不代表已排除全部稳定性问题。

保存仍严格校验模块和背包快照，`is_saved_from=1` 仅作为请求元数据；`interaction_data.fight_time` 必须为非负安全整数，报告不进入 ROLE_DATA。700002 特定胜利调用点恢复角色、背包和关卡保存标志，由同一次原 builder 生成快照。用户已批准按原关卡物品表重建 700002/700003 翻牌：候选数量均为 1，从未弃掉的候选中等概率选 1 件，弃牌费用 0；数量、概率和费用不是原服规则。700002 已实测领奖，700003 尚待完整验收。700004 的 type 12 成品装备原生 factory 已静态定位，离线奖励接入尚未实现。

r11 完整工具测试 **393 项通过（14.52 秒）**，其中桥接 **150 项（5.05 秒）**，`node --check` 通过，执行者为 `bridge_tests`。ZIP CRC、签名 v1/v2/v3 和 315 份原资源字节核验通过。原子失败和重复响应仅完成 Mock 契约测试，未模拟真实断电或重复网络回包。700003 本轮仅教学捕宠自动回村，尚非完整通关/翻牌验收；商城只通过新手教学。700004 成品装备奖励、讨伐任务、普通商城功能、称号列表、一般宠物出战切换、后续养成、其他角色/关卡和 ARM64 真机兼容尚待完成。r1–r10 为先前实验包。

## 签名

生成的文件必须单独签名。测试签名与原版不同，无法作为原版的覆盖更新；当前只在专用模拟器中验证，不操作用户手机的游戏或存档。

现有 `SignApk.java` 接收输入 APK、新输出 APK、既有 DER 私钥与 DER 证书四个参数，启用并校验 v1/v2/v3。打包器不创建或读取签名密钥，也不自动调用签名。密钥不得写进代码或打印到日志；大 APK 构建与签名应等待最终桥接脚本和运行方案确定后执行。

## 数据与密钥

原始 APK 保留不变。配置解码器的 `decode_table(payload, key)` 接收内存中的八字节密钥；不要把客户端密钥写进代码、命令行或日志。下载、解码配置、运行时二进制和测试签名密钥只放在已忽略的产物目录中，签名私钥权限为 `0600`。Git 中不保存游戏资源或密钥。

## V5.1 隔离融灵验证工具

目前为 DEBUG_ONLY / PARTIAL；完整融合及真灵保存未实现。详情见 [本轮报告](../../docs/zmxol-offline-v51-report.md)。

- `prepare_fusion_materials.py PROFILE CONFIG NEW_OUTPUT`：生成221/Lv75、229/Lv60普通测试宠物副本，保留原宠/收据/余额。拒绝覆盖输出；不直接写两种灵元丹数量。
- `prepare_fusion_resources.py ORIGINAL_APK NEW_DIRECTORY`：核对旧原APK SHA，提取221/229/9001/9003的12份原模型；目录不能已存在。预览已局部验证，战斗特效未验。
- `debug_true_spirit_entry.py PRODUCTION_BRIDGE NEW_SCRIPT`：生成独立诊断脚本，保留生产源。只有原YJTownScene和显式一次性触发文件才调用原融灵界面；可选独立材料触发经原工厂发503344–503347各100。重复明确触发是再次发测试材料，不是业务幂等。

仅限已经完整备份、哈希核对的root专用模拟器和派生测试档；不要替换正式存档或原APK。资源目录需置于设备 `files/DEBUG_ONLY-assets/`；入口触发为 `files/DEBUG_ONLY_true_spirit_entry`，材料触发为 `files/DEBUG_ONLY_grant_fusion_materials`。调试脚本只在已知15.7.2 ARM64桥中使用。测试完恢复完整备份和生产桥，清除设备触发文件/隔离资源，sync并核对哈希及断网冷启。

## V5.2 独立真灵融合实验

`debug_fusion_response.py SOURCE PROFILE NATIVE_TEMPLATE NEW_SCRIPT --experimental-fixed-9001` 生成隔离桥，使用配套 `debug_fusion_response.js`。限定V5.1的4405/221与4406/229测试宠物；拒绝已有真灵模块/收据、其他角色及实例冲突。模板须为原9001工厂经serializer输出的29字段默认对象，不能普通宠物JSON冒充。

设备还须显式放置 `files/DEBUG_ONLY_enable_fixed_fusion` 才能准备458成功体。原操作真实消费材料与两宠，经原工厂生成9001/4407；固定兼容结果不代表原概率或继承公式。私有收据与独立 `true_spirit_bag` 同时原子提交；503345/503346从原对象查询余额并随收据恢复。普通快照保持原JsonCpp int64文本。

`DEBUG_ONLY_true_spirit_entry`打开原融灵页；同时放置`DEBUG_ONLY_true_spirit_bag`则打开原完整真灵属性窗口。`DEBUG_ONLY_replay_fusion_response`仅做受同一守卫保护的重复消费诊断，不能称网络层原包重放。必须先完整备份和核哈希，仅用于专用root模拟器；完成后恢复原档/生产桥，移除全部DEBUG标记和资源。详见[V5.2报告](../../docs/zmxol-offline-v52-report.md)。出战cmd469仍失败，未构建新APK，生产源未启用实验。

## V5.3 原真灵出战状态实验

`debug_spirit_state.py FUSION_BRIDGE NEW_SCRIPT` 在V5.2生成桥上增加469持久化与请求身份绑定，使用配套JS。只接受角色1/rid10001、committed融合收据与可证明的原生1/2状态转换；原五宠休息互斥变化随独立真灵背包一起保存。失败锁住存储，重启以实际持久档恢复；不发奖、不改概率、不伪造属性。原模型资源路径在真灵ROLE加载前注册，支持使用状态冷启。仅用于已有完整备份的root专用测试环境；生产源和历史APK不变。18项新增pytest与实机边界见[V5.3报告](../../docs/zmxol-offline-v53-report.md)。
