# 冲突与纠错

- `ccbi/Beast/Main.ccbi` 与 `BeastMainUIController` 实测属于机械研究所，不能作真灵入口；应使用 `YJBeastBoardLayer` 和 `YJBeastMixLayer`。依据本轮两组真实截图/日志，RUNTIME_VERIFIED。
- 2024攻略只列五档品质不证明15.7.2没有其他品质；按原配置与UI核对。
- 原普通宠物252圣佛邪君不是原融合主宠名单成员，不因它是最终形态就认定可融灵。原主宠弹窗与beast_mix_rule交叉验证。
- Lua `fission` 复制对象指针、修改32位容器计数，不创建合法唯一实例；禁止迁移为离线发宠物或融合实现。全部偏移UNVERIFIED_OFFSET。
- 页面访问失败不表示攻略不存在，不填写其规则。
