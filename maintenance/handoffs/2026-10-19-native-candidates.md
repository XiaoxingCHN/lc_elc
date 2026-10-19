# 维护交接：2026-10-19 原生候选包

## 用户目标与已确认边界

继续两阶段入库未完成工作，构建三端候选包；用户随后授权子代理先上线服务端。客户端仅本地候选，不覆盖 releases，不推送。服务端独立记录在 [上线交接](2026-10-19-server-deploy.md)。

## 当前权威源码、分支和版本

clients/app 1.1.0+3；分支 codex/two-stage-receipt-plan，未提交工作树。源为 source-client-two-stage-receipt-20261019.json，150文件，tree SHA256 42f0e5d1dbd64f7611d25d025e53ae3e9a1577631de9a345e3d2ead24f4a1c27。三端副本逐文件核验均无差异；历史成品不改。

## 已完成工作与实际证据

- Android：WSL Ubuntu22.04、Flutter3.47.7、JDK17、SDK36，offline pub和assembleRelease均exit0。APK SHA256 4caabcdcd9d10ba60e8ce2b01ad067a835b15fa667fe69dc9e85f791bf5e1deb；apksigner verify exit0，既有公开证书8b4c…ff43匹配，沿用debug签名身份，非商店正式签名。
- Windows：Flutter3.47.7、MSVC14.44.35207、CMake4.1.1/Ninja，最终隔离完整bundle构建exit0，含VC143 CRT；ZIP SHA256 fd94b74f77431aa4b797eef1500755fe192878c34c1ef45f5065e73ba0949e2e，26文件，未签名。独立APPDATA/LOCALAPPDATA隐藏启动8秒进程存活，随后按可执行路径核对关闭；仅为进程冒烟，不是界面验收。
- Linux：WSL Ubuntu22.04、Flutter3.47.7、clang14/CMake3.22.1/Ninja，offline pub和release构建exit0；17文件bundle的tar.gz SHA256 739700070f6836f5c78650f936a28742c211cd8a0dc3b7e0be9227eb3a14aaec，执行权限0755；7个ELF ldd exit0，无缺失依赖。实际SDK为既有本机登记载荷路径，未修改历史源码。
- tools/build_client.py 新增可选 --gradle-cache，将Android构建缓存隔离；维护测试 `python -m unittest discover -s maintenance/checks -p test_maintenance.py` 8通过exit0，TEMP/TMP指向本轮构建目录。
- `python tools/repo_check.py --output maintenance/audit/native-candidates-repo-check-20261019.json` 49检查通过、exit0；既有 production-py312-rebuild 离线载荷提示仍在，未运行 --verify-payloads。`git diff --check` exit0。
- 初始维护测试因沙箱临时目录权限失败，不算通过；指定可写临时目录后通过。Windows初始下载、沙箱编译及默认安装目录失败均留日志；最终修复只在隔离生成配置和私有依赖副本内完成。PDFium5200用既有离线archive及SHA256，未改共享pub cache或业务源。
- 构建默认服务器为 http://127.0.0.1:18069、数据库 lc_candidate_test，供本地候选验收；不是生产默认发布包。

完整产物、逐文件hash、证书及检查见 [候选审计](../audit/native-candidates-20261019.json)。日志和本机适配配方位于 local/build/native-candidates-20261019；Windows源副本 local/build/client-windows-20261019T151729709，Android源副本 local/build/client-android-20261019T151453585941，Linux源副本在该目录 linux-work.txt 指向的WSL临时目录。

## 剩余工作与阻塞

Linux/Android原生启动、三端界面操作、OS安全存储本轮往返、真实设备扫码和实体打印未执行，不能用编译、Windows进程存活或历史通过替代。三端仍是candidate，未登记为新releases。Linux动态依赖检查只代表当前Ubuntu22.04环境；Windows/Linux未签名，Android仍是已登记debug证书。

## 依赖和产物

产物在 local/build/native-candidates-20261019 两个完整桌面压缩包，Android APK路径在audit。签名私钥只在本机Git排除位置不透明使用，审计只保留公开证书指纹。所有新包来源仍为既有冻结manifest。

## 生产状态和回滚

主代理客户端构建没有生产读写。用户另授权deploy_server子代理服务器上线并提供本轮认证；其最终结果与备份、回滚定位以独立服务端交接及audit为准，不能将最初认证阻塞推断为最终上线结果。
