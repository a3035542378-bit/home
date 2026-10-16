# 15.7.2 V3 工程事实核查

日期：2026-10-14，Asia/Shanghai。本轮需求为真灵优先、觉醒契约调查及质量门禁；联网复原不实施。此文记录开始时基线，后续运行结果见验收报告。

## 工程与保护

- 当前分支 `master`。开始时已有大量 QQ 后端修改及未跟踪 zmxol 工具、文档；保留这些内容，不提交、不重置、不清理产物。QQ API、数据库和 TaskEngine 不属于本轮修改范围。
- 四份指定核心文档、稳定性报告及指定 APK 均实际存在，已读取。矩阵仍为103调查单元；这是调查数量，不是完整恢复数量。
- 历史记录存在版本冲突：ai-context、矩阵和构建记录局部仍写“新包待冷启”，而后出的稳定性结构化报告已记录安装与冷启成功。历史结论分层保留；不能把758/40历史数字当本轮结果。
- 原APK指纹本轮重算一致：11.6.0 `ecff6494a962e066812434497282adb614c0163cb7be856c1f64be36861e3d6a`；15.7.2 `1d87033ad10f66f21968ac8cdff0a405063391ab8145152b27bec6861804567f`。未改写原包。

## 指定稳定性包

| 项目 | 本轮核查 |
| --- | --- |
| 文件 | `artifacts/zmxol-offline/squad-build/15.7.2-mail-stability-signed.apk` |
| 长度 | 2,084,235,402 字节 |
| SHA256 | `2498df95fd9e3e09019cc96eb2b8ff8e530e7ed258bd203a3a61945a4e7d7246` |
| 包名 / 版本 | `com.zmxyol.union.uc` / 15.7.2 / versionCode1532，实际设备dumpsys核查 |
| 签名 | 本轮独立ApkVerifier确认v1/v2/v3，证书SHA256 `baffa7a881cc27a329e17853c18a538b1f01ad6d3845514bcd48e9c4095060b9` |
| 初始源 / 设备脚本 | `4d977d982224b10f884802e312e4146b696557272566c0199cfbd41345352719`，设备实际sha256sum一致 |
| 全ZIP CRC | 历史构建记录通过；本轮映射所读取成员CRC由zipfile校验，未重跑全包CRC |

签名验证证据：[apk-signature.json](../artifacts/zmxol-offline/v3-20261014/apk-signature.json)。本轮工作源后续发生SDK修复，不能继续称它与该APK一致。

## 设备、工具与存档

专用 `emulator-5576`，AOSP Android ARM64，`ro.kernel.qemu=1`，包名如上；开始时ADB为root，Python3.13.5、Lua5.4.8、Node、OpenJDK、JADX及llvm-objdump可用。apktool不在PATH，现有构建工具直接处理DEX/AXML，非必需。原临时Java源目录实际为空，SDK调查重新从本轮APK DEX反编译，不能声称读取了已消失源码。

测试前导出 `files/shared_prefs` 共354条，tar可读，备份权限600。备份tar SHA256 `e6ee12f02fa901722a45775afc955bb23bd2ae6c0f2ecf451fb60fc2d4571af8`；主save SHA256 `ec8c83c4364f02d49c7599bf1fe5bd56a677f7fae8dad61fddc748030cca637c`，11,810字节。设备重启恢复后再次导出，主save逐字节一致。保护文件位于 `artifacts/zmxol-offline/v3-20261014/`，不作为公开分享材料。

角色90级；普通宠物4400/252、4399/210、4401/252、4402/252、4403/252共五只；没有true_spirit_bag。历史“四宠”只适用于900600002领取前，不适用于本轮开始状态。保存的装备、余额、技能及邮件收据一并包含在完整备份中，不打印敏感字段。

开始时飞行模式1/Wi-Fi0，IPv4/IPv6 OUTPUT仅允许loopback；AVD重启后规则会重置，测试前重新插入loopback允许与外网DROP。APK无INTERNET权限。未请求官方服务器。

## 实现状态与本轮计划

真灵根模块白名单拒绝 `true_spirit_bag`，未适配457–470等原协议。普通pet实例不替代真灵；无法靠添加白名单或返回空成功形成闭环。先重新核查逐ID配置、资源分页、原sender/factory/loader及材料映射，再评分选择；关键契约不足时给出阻塞报告。

觉醒教学已保存虬龙棍及Lv2石实例；常规费用、随机结果和失败语义缺证。并行只读调查四个sender与consumer，共享桥接修改串行。优先复用原工厂、原序列化和现有原子存档，不新增统一资产框架。

公共门禁发现原稳定包断网启动存在FN SDK未捕获SecurityException；历史冷启成功不证明它不会间歇发生。本轮新增针对原IOException失败通路的修复候选，必须单独实测，不能借单元测试宣称修复。

新增文件和源改动及最终数量见[本轮报告](zmxol-offline-v3-report.md)。真灵获取、培养、战斗和冷启尚未通过，禁止构建“真灵已恢复”的新交付包。
