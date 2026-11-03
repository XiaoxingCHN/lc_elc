# 任务：bore 公网入口 P1 本地隔离实现

> 记录顺序说明：本轮先按 Codex 要求落地实现文件，随后补建本任务单（已如实记录，不伪造成"先建单"）。

- 目标/用户场景：为"仅用 Odoo 账号登录、公网只读优先、日常页面统一自有 UI"的公网访问方案提供 **P1 隔离入口实现**：
  默认拒绝的 Nginx 白名单、真实 bore 隧道链路、可信边缘 PROXY 来源 IP、登录端点限速，可在本地重复验证，可迁移到受控节点。
- 当前问题及复现方法：旧候选只有零散 nginx 片段与自写 mock，无法证明真实链路；bore 官方不支持 PROXY protocol；公网节点/标准 443/真实 Odoo 尚不可用。
- 验收标准：
  1) 模板与脚本落在 server/ubuntu22.04/bore，含 README 与测试，不硬编码本机用户名/F 盘路径；
  2) 真实 Nginx 配置语法与运行通过；Host/方法/精确路径白名单；默认拒绝；路径归一化/编码绕过被拒；
  3) 完整链路 = 公开边缘 Nginx(stream, 不接收客户端 PROXY) → bore 隧道 → 入口 Nginx(TLS+PROXY) → 上游；两来源不互相误封；
  4) 伪造 XFF/Forwarded 被覆盖；直接访问入口/隧道断开失败关闭且上游零请求；伪造 PROXY 前缀不提升信任；
  5) 登录端点限速：A 超限、B 正常、伪造 XFF 不能逃逸；
  6) 明确 synthetic 上游非 Odoo，不声称真实会话/权限/库存验收。
- 允许修改目录/接口：server/ubuntu22.04/bore（新增）、local/build/bore-p1-20261026（证据，Git 忽略）、maintenance 文档、CURRENT_STATE/CHANGELOG 追加。
- 业务不变量/依赖：不改 Odoo 源码/数据库/生产配置；库存权威仍为 stock.quant/stock.move；不新增认证系统；不安装系统级软件（测试用本地解包 nginx 与 bore 二进制）。
- 负责人/协作者及分工：DSH 实施+原始证据；Codex 审查/决策；用户提供环境与最终验收。
- 分支/起始commit/源码manifest：codex/two-stage-receipt-plan，HEAD 14cf1ef44c6da1a1c1e4a77bbe51c446023a1e71；当前 server manifest source-server-team-web-phase1-20261025.json（175 文件）；本轮新增文件后另建新快照，旧 manifest 不改写。
- 环境与凭据获取方式（只写位置，绝不写值）：WSL Ubuntu 22.04 本地；nginx 1.18.0（Ubuntu deb 非 root 解包）、bore-cli 0.5.3（官方 MIT 发行包）、OpenSSL 3.0.2、Python 3.10.12。测试证书为本地合成 CA，仅存于 local/（Git 忽略）。
- 实施步骤：
  1) 上游研究：bore 官方源码确认无 PROXY protocol 支持（MIT）；因此边缘必须由成熟 Nginx stream 生成 PROXY；
  2) 模板：默认拒绝 allowlist（按 lab_team_web 真实控制器/JS 端点）、头覆盖策略、限速钩子；
  3) 脚本：本地生成证书、启动入口 Nginx 与公开边缘 Nginx、bore server/client、合成上游，执行矩阵断言；
  4) 修复边界：动态 key 用正则单段匹配；方法不匹配统一 403；路径绕过用 --path-as-is；上游命中计数；仅清理本轮进程。
- 测试命令、实际结果与退出码：见下节"测试结果"。
- 未验证项及风险：真实公网节点/标准 443/真实访客拓扑、真实 Odoo 会话与权限、自动续期、ETA/Flutter 客户端迁移、生产部署均未做；bore 官方不支持 PROXY，真实边缘必须自带 PROXY 能力。
- 发布文件、hash和回滚点：新增 server/ubuntu22.04/bore/**；需新建 server 源快照并 --activate；回滚=删除该目录并恢复旧 active manifest 指针（旧 manifest 不改写）。

## 测试结果（本轮）

- 契约测试：`python3 -m unittest discover -s server/ubuntu22.04/bore/tests -p test_config_contract.py` → **Ran 9 tests, OK**。
- 本地链路验证：`NGINX_BIN=... MODULE_SO=... BORE_BIN=... bash server/ubuntu22.04/bore/scripts/verify-local-entry.sh`
  → **SUMMARY PASS=94 FAIL=0，exit 0**；证据 `local/build/bore-p1-20261026/run-console.log`、`run/results.jsonl`、`run/summary.json`。
- 失败路径：`bash server/ubuntu22.04/bore/tests/test_failure_paths.sh` → **FAILPATHS PASS=10 FAIL=0**（端口占用/WORK 复用/已有服务不受影响/无子进程残留）。
- 运行时来源：`bash server/ubuntu22.04/bore/scripts/fetch-runtime.sh --verify-only` → **ok=8 bad=0**。
- 隔离限制：合成上游不是 Odoo，不验证真实会话/权限/库存；本结果不等于公网安全验收或 P2/P3 通过。
