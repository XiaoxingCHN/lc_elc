# 任务：P3 服务端生产更新（2026-10-28）

- 目标：用户在Git推送后明确要求“服务器端更新”，将已冻结P3部署到既有lc-nas生产Odoo及项目回源白名单。
- 授权：允许项目模块升级、必要重启、部署前一致备份与只读核验；不改DNS、其它服务、Docker、爬虫或客户端，不读取/输出凭据。
- 来源：commit b3bcbf244e44939c6d481e3f97f11579cdf9ee99；source-server-p3-web-20261028.json，250文件，tree fc2d538da7965c2def6b66f8e551948e19d282641f40883bcd45e40dddf5ab43。
- 范围：以实际生产文件比对确定必要模块（预期lab_workflow 19.0.2.0.0、lab_team_web 19.0.1.1.0）及项目专用Netlify TLS网关，保持stock.quant/move权威、原袋QR不变、原LAN vhost和更新通道可用。
- 凭据：仅通过已配置SSH host和服务器终端交互使用；不保存值。
- 前提：新做停服一致db.dump+真实filestore备份，并核验配对清单、非空附件数、pg_restore列表、hash、旧模块和网关源码；旧P2不一致补备不可当本轮回滚点。
- 当前检查：lc-nas可达，odoo/nginx active；sudo -n true不可用，sudo -n -l返回需要密码。生产Python3.12.15与现有依赖已核对；受保护源码/DB版本将在root preflight核验。尚未停服、升级或改变生产业务。
- 已准备：/home/hbut/lc-elc-p3-20261028/run_update.py，operator.tar.gz SHA b959c0bf4e6670604d402df39756e7cc909407f489ec237cbe980ee5174fa95d；两模块candidate.tar.gz SHA e3a18d79363d3a945213530cef6d7371244f31a0dc91f5851ac60675b78dee80，11,637,032字节。
- 服务器实测准备验证：Python3.12.15，81个Python源编译、两个bash语法、包/策略验证、1.18兼容gateway渲染和篡改版本负向控制均通过；不是生产业务验收。
- 提权进展：用户随后提供本次凭据；仅在一次性加密SSH会话的内存stdin使用，主机密钥验证且sudo UID0已通过，未保存凭据。
- 实际执行：首轮PID377256在解压阶段因旧P2 helper硬编码白名单拒绝workflow退出；未停服/换码/迁移，Odoo保持active。现已修显式两模块白名单，并新增真实Base.extract回归（128文件、实际版本校验、额外模块/ops拒绝），新operator SHA 0b2c586c0b9aa4c842265e5fdbae7b846627aaa8defa5dcde1ef94aaaeb019ab。
- 当前后台任务：第二轮PID379385，root私有日志/var/lib/lc-elc-deployments/p3-console-20261028-103357/operator.log；启动器已核验首轮进程退出且仅经过preflight/baseline/error，无生产代码/DB变更后才允许重试。脱敏状态/home/hbut/lc-elc-p3-20261028/public-status.json。
- 最终操作门槛：停服精确inactive且无Odoo进程，dump与filestore成套hash/权限/真实data_dir核验，加pg_restore列表非空门槛；成功后仅-u两模块及项目网关、本地HTTP200检查，不将公网既有故障冒充通过。
- 既有故障：更新前lc-bore-netlify.service activating/auto-restart（NRestarts2334，exit1），NAS直接curl正式teamTLS为000；本地更新不能冒充公网恢复，仍需独立核验。
- 分工：Lead执行所有命令/上传/生产动作；Qoder只在local/build/p3-production-20261028编写候选部署辅助和回滚计划，不改冻结源码。
- 步骤：生产只读与运行时→部署包/回滚审核→新一致备份→必要模块和网关更新→HTTP/模块/库存不变量核验→正式交接。
- 未测边界：真实账号写业务、摄像头/实体打印/手机无VPN未测；不将本地Python3.10通过视作生产3.12通过。
