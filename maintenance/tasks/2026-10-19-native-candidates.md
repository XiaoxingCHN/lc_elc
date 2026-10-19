# 任务：两阶段入库原生候选包与验证

- 目标/用户场景：继续上一轮未完成事项，构建 Windows、Android、Linux 1.1.0+3 候选包并核对来源、完整性、启动与签名。
- 当前问题及复现方法：上一轮只有已验证候选源码，未重建原生安装包；实体扫码打印与进程内并发夹具仍未完成。
- 验收标准：各端实际构建结果、退出码、环境、完整 bundle／APK、SHA256 和 source manifest 可追溯；Android 与已登记证书匹配；未执行的实机项不得写通过。
- 允许修改目录/接口：tools、dependencies 的必要恢复／构建工具及相关文档、maintenance 登记；local/build 新隔离目录。业务源码如需修正另记录并生成新快照，不改历史成品。
- 业务不变量/依赖：库存和接口规则沿用上一轮；构建不自动授权连接生产。仅使用显式本地测试配置，无真实账号或业务数据。
- 负责人/协作者及分工：主代理负责客户端；用户随后明确授权 deploy_server 子代理处理服务器上线，服务端独立任务交接，避免重叠修改。
- 分支/起始commit/源码manifest：沿用 codex/two-stage-receipt-plan 与未提交工作树；client 源为 source-client-two-stage-receipt-20261019.json，server 源为 source-server-two-stage-receipt-20261019.json。
- 环境与凭据获取方式：仓库已登记 Flutter、离线依赖及本机可用 C++ 工具；Android 只不透明使用已登记私有 key，不读取或输出私钥内容。
- 实施步骤：核对工具和历史配方 → 新隔离源码副本 → 构建与平台检查 → 产物登记和交接。旧脚本仅作参考，不直接运行。
- 测试命令、实际结果与退出码：三端 release 构建最终 exit0；Android apksigner verify exit0，证书匹配；Windows/Android/Linux 每端150源文件匹配；Linux七个ELF ldd exit0、无缺失，tar可执行权限0755；维护测试8通过exit0。见 audit/native-candidates-20261019.json 和 handoffs/2026-10-19-native-candidates.md。
- 未验证项及风险：实体设备、打印纸张与原生服务能力依可用设备验证；生产部署、服务器修改及旧包覆盖不在范围。
- 发布文件、hash和回滚点：产物放 local/build 下，状态 candidate；旧 releases 和旧 source manifest 保持不变，未授权发布或推送。
