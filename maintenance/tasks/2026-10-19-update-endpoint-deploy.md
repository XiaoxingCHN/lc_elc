# 任务：生产客户端更新接口上线

- 目标/用户场景：用户明确选择“现在上线更新接口”；解决客户端可读取库存但更新接口尚未部署的问题。
- 当前问题及复现方法：生产 lab_workflow 19.0.1.1.0，manifest 路由不存在，更新面板报暂时无法检查。
- 验收标准：完整配套备份经实物/hash核验；仅升级 lab_workflow 19.0.1.2.0；服务 active、登录200、三端未发布manifest204；权限隔离、库存数量不变。
- 允许修改目录/接口：既有 /opt/odoo 项目、配套 /var/backups/lc-elc；本任务独立 task/audit/handoff。其他服务/网络/爬虫不在范围内。
- 业务不变量/依赖：库存以 Odoo 为准；不写生产测试库存，不发布 stable。既有生产 Python3.12 venv，无新增依赖。
- 负责人/协作者及分工：部署子代理负责生产和独立记录；主代理负责客户端白屏修复、构建及共享状态文档。
- 分支/起始commit/源码manifest：codex/two-stage-receipt-plan；完整commit见审计；source-server-updater-20261019.json，130文件，源树446e7ada847f86c15572f808c3175723e6e533dea845a0c0fd9e63f6b3ec841e。
- 环境与凭据获取方式：现有 lc-nas 项目连接；专用密钥被拒，改用用户已授权认证，经 getpass/进程内存与 sudo stdin，不保存值。远端受控有效配置显式真实data_dir，root:odoo0640。
- 实施步骤：源清单/包核验→上传独立stage→只读基线→停服务→成套备份及逐附件hash→保留旧源码到addons外→仅换lab_workflow→仅-u lab_workflow→启动→只读/HTTP/权限核验。
- 测试命令、实际结果与退出码：审计记录具体命令；打包130、已部署addons107文件匹配；134附件逐项hash匹配；2备份实物hash、pg_restore --list0；6生产HTTP及4本机LAN HTTP通过；5实际账号权限检查通过；升级、最终验证均exit0。完整证据见 maintenance/audit/update-endpoint-deploy-20261019.json。
- 未验证项及风险：未发布更新包，真实认证HTTP包下载和客户端安装不在本轮验证范围；未做完整恢复演练或离机备份。
- 发布文件、hash和回滚点：仅服务端上线；本地包sha287b9fc67a64713c2ed3aa4ce0ac5a444ede29480351d79df98e33e3ae75b902；本轮备份 /var/backups/lc-elc/20261019T131258Z-before-update-endpoint，旧模块在其module-source-before-upgrade/lab_workflow。
