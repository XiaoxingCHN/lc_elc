# 维护交接：2026-10-27 P2 证据加固

## 用户目标与已确认边界

恢复可信 P2 验收并修复实际缺陷。本轮授权本地源码、隔离夹具/测试、登记表、文档和新源快照；生产仅内网只读，不部署、重启、查库、导入或改网络。并行任务均使用 DeepSeek-Flash · Qoder CN；未遇限额，未使用获准的 WorkBuddy 备用路由。

## 当前权威源码、分支和版本

分支 codex/two-stage-receipt-plan，起始/当前 HEAD 为 14cf1ef44c6da1a1c1e4a77bbe51c446023a1e71；未提交、推送或切分支。lab_team_web 候选 **19.0.1.0.5**，lab_catalog 候选 **19.0.2.0.5**。新快照：[source-server-p2-evidence-hardened-20261027.json](../registry/source-server-p2-evidence-hardened-20261027.json)，旧 final3 与独立审计保留。

## 已完成工作与实际证据

- 最终真实 Odoo/Nginx/bore/Chrome 轮次 **run.cf3QjW：127 pass、0 fail、0 blocked、0 skip，exit 0**，其中真实 UI 28 步全部通过；独立计数/状态检查一致，运行输入哈希稳定。
- P1 116/0；bore 167 项（WSL 165 通过、2 缺 Node 跳过，Windows 补测 2/0）；lab_team_web 87 项（86 通过、1 真实 Odoo HttpCase 跳过）；lab_catalog 23/0；实际 manifest hook 生命周期 7/0、数据库回滚。
- authority 保端口、生产端口参数化、严格 CSP、原生退出 + CSRF、动态详情/旧 Cookie 失效、Ed25519 下载清单独立验签均已复核。
- asset IPv6 首地址黑洞已修为全候选安全校验后的有界回退，未放宽 SSRF/TLS/重定向/大小边界。bore 启动失败不能继续报 ready。
- 官方 Noto CJK 私有字体恢复，中文搜索/详情截图已目视确认。测试私钥在隔离 WSL 原生文件系统，实测 0600，不入 Git。

详见[完整审计](../audit/bore-p2-evidence-hardening-20261027.md)、[最终汇总](../../local/build/bore-p2-20261026/runs/run.cf3QjW/summary.json)、[浏览器证据](../../local/build/bore-p2-20261026/runs/run.cf3QjW/browser/browser.json)。results SHA256 为 a478fecf043f8f9647c78ba56b3ee3d394bdde9ec51f9da45241d03e83560f9e。local 链接仅供本机复核。

旧 77/0 不再作为完整通过依据；本轮失败轮次保留真实 fail，没有追改为 pass。最终仓库检查：python tools/repo_check.py：PASS，52项检查、0错误、exit 0；git diff --check exit 0。既有 production-py312-rebuild 尚未构建，完整离线闭合未建立；全量payload校验未执行，新字体载荷已独立核对官方SHA256。

## 剩余工作与阻塞

本轮验收加固已完成。尚未做生产部署、公网/标准 443 验收、真实账号生产流程、真机更新安装、写业务 UI 与 EDA/Flutter 旧调用迁移。夹具详情未导入参数/袋数据，不能外推那些业务已验收。

## 依赖和产物

本地使用 Nginx 1.30.6、bore 0.5.3、Chrome 156.0.8078.47，隔离 Odoo 19/Python 3.10.12/Werkzeug 2.0.2；依赖与其 requirements 一致。官方字体 [来源登记](../registry/bore-p2-fonts-20261027.json)及[payload 登记](../registry/payloads.json)。公开测试清单用 test-only key，合成 APK 不可安装，不冒充生产发布。恢复测试环境与命令见 [bore README](../../server/ubuntu22.04/bore/README.md)。

## 生产状态和回滚

[只读记录](../audit/production-intranet-readonly-20261027.json)：生产磁盘 manifest 19.0.1.0.0，DB 安装版本未查；Nginx 1.18.0 不支持 proxy_cookie_flags，候选安全头未部署。内网可达不等于公网可达。本轮没有生产变更或回滚；未来部署须独立授权并先准备兼容方案、备份与回滚证据。
