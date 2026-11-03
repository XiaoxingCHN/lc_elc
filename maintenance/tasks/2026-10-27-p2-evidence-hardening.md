# 任务：P2 验收证据加固与同源修复

- 目标/用户场景：继续 LC_ELC 工程，先恢复可信的 P2 验收基线；子代理统一使用 DeepSeek-Flash · Qoder CN，主代理负责范围、复核和最终结论。
- 当前问题及复现方法：当前 browser_flow.py 的 search/退出由测试自行 fetch，未操作真实 UI；匿名状态将未知错误归为 anon；summary.json 缺 blocked/skip；本地 wrapper 注入 CSP_CONNECT_EXTRA 允许另一个 origin；代理 Host/X-Forwarded-Host 使用 $host 丢失外部非标准端口。此前 77/0 仅为历史脚本结果，不作为本轮独立验收通过。
- 验收标准：严格 CSP 下无浏览器安全错误；真实 UI 登录/搜索/详情/刷新/退出；查询与内容一致、非匹配项排除；退出 303、显式匿名或 SessionExpired、/lab 保护、旧会话失效；证据脱敏且同轮 JSONL/summary/exit 一致；runner 安全；适用 P1/模块回归通过；准确交接与新不可变源码快照。
- 允许修改目录/接口：server/ubuntu22.04/bore、lab_team_web 候选、lab_catalog/controllers/asset_cache.py 与其版本/测试（本轮实际复现 IPv6 首地址黑洞导致504后的最小回退修复）、与本轮测试必要的 local/build 忽略材料、maintenance/tasks/audit/handoffs/registry、docs/operations/CURRENT_STATE.md 和 CHANGELOG.md。只在审查后作最小修改。
- 业务不变量/依赖：库存权威与角色边界不扩大；生产只读，不部署/重启/导入/更改 DNS/防火墙；无真实凭据入 Git；旧快照与成品来源不可改写。
- 负责人/协作者及分工：lead 协调/复核/登记；Qoder Flash 子代理分别负责独立证据审查、CSP 来源研究、后续互斥范围实现；具体 write scope 在派发时声明。用户追加授权：Qoder 达到配额/限流或不可用时可切换 Deepseek-V4.1-Flash · WorkBuddy AI（magpie / workbuddy-ai/deepseek-v4.1-flash）；正常任务不切换，实际路由需核验。
- 分支/起始commit/源码manifest：codex/two-stage-receipt-plan，14cf1ef44c6da1a1c1e4a77bbe51c446023a1e71；source-server-bore-p2-final3-20261026.json。工作树已有 69 项，保留既有修改。
- 环境与凭据获取方式：现有 WSL 隔离 Odoo/PostgreSQL、Nginx/bore/Chrome 和合成账号，位置在 Git 忽略的 local/build；不输出凭据。
- 实施步骤：独立审查 → 冻结修复范围 → 子代理实现与有意义测试 → 主代理复核及真实链路 → 更新证据/交接/新快照。
- 测试命令、实际结果与退出码：待本轮执行；历史结果不复用。
- 未验证项及风险：公网/标准443/真机/生产升级未获本轮授权；公网图片允许源可能继续 blocked，禁止为测试放开 SSRF。
- 发布文件、hash和回滚点：本轮不发布；候选快照在有效测试后新建，旧 final3 保持不可变。
## 完成记录（2026-10-27）

本轮已完成：P2 run.cf3QjW 127/0/0/0 exit0；浏览器28/0；P1116/0；hook7/0；bore167项（165通过2缺Node跳过且Windows补测2/0）、lab_team_web87项（86通过1HttpCase跳过）、lab_catalog23/0。新快照 source-server-p2-evidence-hardened-20261027.json 已创建并激活；repo_check52/0 exit0，diffcheck0。生产无变更。详见 ../audit/bore-p2-evidence-hardening-20261027.md 与 ../handoffs/2026-10-27-p2-evidence-hardening.md。
