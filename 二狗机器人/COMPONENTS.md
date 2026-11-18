# 环境与组件矩阵

|组件|本次记录|来源、用途及限制|
|---|---|---|
|Windows|Windows 11 build 22631，AMD64|本机运行环境。锁屏、RDP 断开、注销、重启等场景另验|
|CPython|3.12.14，MSC v.1944 64 bit|本机随 Codex 提供的 Python 运行时；新部署可用 Python 官方同版本。核心仅使用标准库，PSF 许可证|
|SQLite|3.53.1|上述 Python 的 sqlite3 运行库；单机本地 WAL、FULL 同步、3 秒忙等待。公共领域|
|微信客户端|Weixin.exe 4.2.0.13|已安装的腾讯客户端，第三方专有组件，本项目不再分发。文件 SHA-256 为 EAAA1C6C6123CE9887E5C67B60D905D22F09FAC091058F27D2D819E9FF26FC69|
|桌面验证方式|Windows 可访问性界面|实测授权群可定位、编辑区及消息列表可观测。一次发送及本机回显，成员稳定标识与平台级回执待验证|
|Python 接入桥|核心协议 v1|本项目源码。已验证节点认证、群授权、心跳、持久化确认和发送租约，测试节点为模拟数据|
|游戏素材|内置规则 v1.0|项目内编写的规则、数字盘面及有限词表，无外部图片、音乐、题库依赖|
|天气及快递|Open-Meteo、快递鸟、DHL|远程服务，不打包第三方 SDK。接口凭据与本地业务文件分开配置|

本机项目可用 Python 标准库复现；用户自装 Python 中 SQLite 小版本可能不同，须记录新环境的测试结果。Windows 10、Server 及其他微信版本尚待验证。

[Python](https://www.python.org/) · [SQLite WAL](https://sqlite.org/wal.html) · [Open-Meteo](https://open-meteo.com/) · [快递鸟](https://www.kdniao.com/) · [DHL Developer](https://developer.dhl.com/)

