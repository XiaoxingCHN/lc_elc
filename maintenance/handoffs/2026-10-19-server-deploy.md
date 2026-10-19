# 维护交接：2026-10-19 服务端两阶段入库已上线

## 用户目标与已确认边界

用户明确授权子代理优先上线本项目服务端，并随后提供本轮项目 SSH 密码认证。密码只经 getpass 在进程内存持有并经 stdin 提供 sudo；没有保存到文件、环境、日志、Git 或记忆。仅操作项目 Odoo 模块与必要备份/服务重启，没有改其他服务、网络、Docker、采集或写测试库存。

## 当前权威源码、分支和版本

权威源 server/ubuntu22.04；分支 codex/two-stage-receipt-plan，起始 commit 28dd8bf032404eee5d1196aff786fd96b2cf8b52，未提交推送。

生产现已核验三个模块 installed：lab_inventory 19.0.1.0.0、lab_catalog 19.0.2.0.3、lab_workflow **19.0.1.1.0**。104 个业务 addons 文件逐项 SHA256 匹配 maintenance/registry/source-server-two-stage-receipt-20261019.json（源树 87976a0286517ba554e6c268c65e4ad9054ad64284b22524419c47f76f78f4a8）。

部署中修复运维保留目录缺陷后，最终维护源为 maintenance/registry/source-server-two-stage-receipt-opsfix-20261019.json，127 文件，源树 d2f0775da8e67b0e752516c42b9b9764006970e541cebb4473219aa6300f2cfe。业务 addons 未变；仅 upgrade_modules.sh、lc_odoo_conf.py、lc_ops_tests.py 三文件补同步至实际本轮工具目录 /opt/odoo/deployments/two-stage-20261019-a1，逐文件 hash 核验，原始包与旧工具另存未覆盖。

## 已完成工作与实际证据

完整机器可读记录 maintenance/audit/server-deploy-20261019.json；任务 maintenance/tasks/2026-10-19-server-deploy.md。

1. 核实主机 lc-nas、数据库 LcHardwareHouse、生产 addons /opt/odoo/custom-addons，磁盘约 202 GiB 可用。未打印真实配置或业务记录。
2. 原生产配置未设 data_dir，真实 filestore 位于 /opt/odoo/.local/share/Odoo/filestore/LcHardwareHouse；运维默认 /var/lib/odoo 不存在。为防漏备，在远端受控 stage 生成显式真实 data_dir 的有效配置副本，root:odoo 0640，原配置不变，未拷贝至本地。备份包含 154 文件、47,713,300 源字节。
3. 升级前保存完整三个旧模块源码，包含远端额外历史文件；原 lab_inventory 无差异、lab_catalog 只有 XML 末尾空白差异。配套 DB/filestore 已完成备份并逐项核验 SHA256，pg_restore --list exit 0。
4. 首次 upgrade_modules.sh --code-dir 升级 exit 255：工具在 addons 内保留 `.pre-upgrade-时间` 目录，Odoo 19 Manifest 扫描拒绝非法模块名。服务 fail-closed 保持 inactive。定位后检查绝对路径包含关系，把本轮三个旧目录移至 stage/old-modules；未删除或覆盖旧源码。随后同工具不带 --code-dir 再执行，exit 0；Odoo 升级与启动成功，日志 ERROR/CRITICAL/Traceback 0。实际 runtime 日志在重试时段 ERROR 0、CRITICAL 0。
5. 主代理同步修复运维脚本：将旧源码保存至配套备份根、校验绝对目标/所有 addons 根/链接/不覆盖，WSL root 108 项故障注入检查、0 失败、exit 0。日志 local/build/native-candidates-20261019/ops-regression.log。修正工具已同步生产 stage，无再次升级或重启。
6. 本轮独立只读生产验证：服务 active、/web/login HTTP 200、匿名 pending API 返回授权错误；新 pending 0、trace 1、历史袋码缺漏 0，两个新唯一约束存在。升级前后 bag 1、quant 2、move 1、operation 1、catalog 695217、location 16 相同，quantity/reserved 总量均 0。旧“无袋数据”是历史快照，不代替本轮事实。
7. 只读且回滚的 ORM 验证 exit 0：2 个操作账号读取待入库列表成功，2 个无权账号与 1 个公共账号被拒；5 个账号直接创建 pending/trace 均被 AccessError 拒绝；pending 只有只读 ACL，trace 无用户 ACL。未创造任何生产测试记录。
8. 读取既有袋生成 PDF，1 页/1 标签/每签 1 QR，131799 字节，SHA256 72c1136b6dce5c3579b1374b4f6cadeebdf5e2f042fe2d38c0c7d7470f50896b；只输出长度/hash，PDF 和业务内容没有外传。
9. 本地 MSYS2 Python 3.12.9 纯逻辑收集 28、通过 23、跳过 5（缺 reportlab）、exit 0。本轮之前的隔离 Odoo/HTTP 验收仍单列在原功能交接，不冒称此次重跑。最终仓库检查由主代理统一执行。

早期专用 SSH 密钥认证失败；尝试备用通用身份被自动审批拒绝，未执行。用户提供密码后成功。输出完整生产日志也被自动审批拒绝，未导出；改为远端提取固定异常类别、代码行号、计数完成诊断，没有绕过拒绝。

## 剩余工作与阻塞

生产服务端已上线，认证不再阻塞本轮已完成任务。尚未实体扫码、相机、扫码枪连续焦点、系统打印与纸张可扫性验收；没有在生产创造待入库数据测写路径，新 pending 标签的完整场景仍依据隔离测试。此次备份没有全量恢复演练，也未离机复制。

## 依赖和产物

未新增第三方依赖。候选业务包 /tmp/lc-elc-two-stage-20261019-candidate-a1.tar.gz，SHA256 7e9789e4c739d379a195e22c607d41b26d40f14650e4f3753c32a8251e53a70e；原始包未覆盖。运维修复小包 SHA256 55945f6def7ade3381225e6407a60b901a33351a1a2917b3272ccd456fd3c687。

实际远端工具、有效配置、部署事实与日志均位于 /opt/odoo/deployments/two-stage-20261019-a1。upgrade.log 为首次失败记录，upgrade-retry.log 为成功记录，deployment-facts.json 为脱敏计数/hash。有效配置属受控私有文件，不可复制到 Git 或交接正文。

## 生产状态和回滚

首份回滚备份：/var/backups/lc-elc/20261019T073840Z-before-upgrade。

- db.dump：110502540 字节，SHA256 3310d7620d63ebaa83d8dd59da9072ace9a62b214c6e05cefaf7a0f1256f7c5a2。
- filestore.tar.gz：14372252 字节，SHA256 5798312ad0648ddc903523b62cb14827b616ee66f0e6fb653e29e6fe19e50698；154 文件与源总字节匹配。
- 旧源码 /opt/odoo/deployments/two-stage-20261019-a1/old-source.tar.gz：11877898 字节，SHA256 b450005c22ad56eac3dd7db2c90051bec578d5224a727150d7c3dc79df31a50b。
- 可直接恢复的旧目录 /opt/odoo/deployments/two-stage-20261019-a1/old-modules/{lab_inventory,lab_catalog,lab_workflow}；不在 addons 扫描根。

第二次工具运行另产备份 /var/backups/lc-elc/20261019T074111Z-before-upgrade；它的源码指纹已是候选，不能替代首份与旧源码的明确配对。

如需回滚，先备当前业务状态，验证首份 MANIFEST 与 DB/filestore 配对、真实 data_dir、源码 hash 和路径包含关系。停服务，将当前失败源码移至独立受控保留目录，再从 old-modules 恢复旧模块；对首份备份先执行 odoo_restore.py --list / --dry-run，确认后恢复目标 LcHardwareHouse，传入本轮有效配置路径，启动并只读核验。禁止对旧模块再次 -u。数据库恢复会回退备份后的业务写入，需核对当时授权与维护窗口。此次没有执行恢复，也未声称备份已离机保护。
