# P2 证据加固验收（2026-10-27）

本轮本地隔离验收已完成：**127 pass / 0 fail / 0 blocked / 0 skip，进程退出码 0**。生产仅做授权的内网只读核对，未部署、重启、查询数据库或修改配置。

任务：[任务单](../tasks/2026-10-27-p2-evidence-hardening.md)；交接：[本轮交接](../handoffs/2026-10-27-p2-evidence-hardening.md)。候选版本为 lab_team_web **19.0.1.0.5**、lab_catalog **19.0.2.0.5**。

## 结论与证据

最终轮次为 **p2-20261027T080126Z-run.cf3QjW**。以下 local 链接是本机忽略材料，不随 Git 分发。

| 检查 | 实际结果 | 证据 |
|---|---|---|
| 完整 P2 | 127/0/0/0，exit 0 | [summary](../../local/build/bore-p2-20261026/runs/run.cf3QjW/summary.json) |
| 真实浏览器 UI | 28/0，exit 0，console/network errors 均 0 | [browser](../../local/build/bore-p2-20261026/runs/run.cf3QjW/browser/browser.json) |
| P1 真实代理回归 | 116/0，exit 0 | [P1 汇总](../../local/build/p2-lead-20261027/p1-regression-summary.json) |
| bore 逻辑测试 | 167 项：WSL 165 通过、2 跳过；缺 Node 的 2 项已用 Windows 现有 Node 补测通过 | [逻辑汇总](../../local/build/p2-lead-20261027/logic-summary.json) |
| lab_team_web | 87 项：86 通过、1 HttpCase 跳过 | 同上；真实 Odoo 场景另由本轮 P2 覆盖 |
| lab_catalog | 23/0，覆盖地址回退、私网混入、TLS/SNI、总预算和慢流 | 同上 |
| manifest 命名 hook | 7/0，真实 Odoo 环境调用，数据库回滚 | [生命周期](../../local/build/p2-lead-20261027/lifecycle-proof.json) |
| 下载清单签名 | 下载文件独立 Ed25519 公钥验签通过 | [验签](../../local/build/bore-p2-20261026/runs/run.cf3QjW/signature-verification.json) |
| 源码稳定性 | 整轮 16 项运行输入哈希未变 | [输入哈希](../../local/build/bore-p2-20261026/runs/run.cf3QjW/acceptance-input-hashes.json) |

results.jsonl 共 127 行，SHA256：


`a478fecf043f8f9647c78ba56b3ee3d394bdde9ec51f9da45241d03e83560f9e`

独立 --check-evidence 重算一致：evidence_integrity=pass、run_status=pass、run_exit_code=0、run_passed=true。该工具会分别报告证据完整性和业务结论，不将证据完整的失败轮次称为业务通过。

中文截图已目视复核：[搜索](../../local/build/bore-p2-20261026/runs/run.cf3QjW/browser/shot-03-search.png)、[动态详情](../../local/build/bore-p2-20261026/runs/run.cf3QjW/browser/shot-04-detail.png)。搜索框实际输入 TEST-R-10K，结果仅电阻，详情来自结果卡片并显示实验室库存 25；搜索前后截图哈希不同。夹具未导入参数/袋数据，因此不据此声称参数/袋业务完成。

## 修复内容

1. 原入口用 $host 去掉外部端口，Werkzeug 将 303 绝对化到不同 origin。现精确校验 $http_host、保留完整 authority、覆盖伪造转发头并清空 X-Forwarded-Port。@PUBLIC_PORT@ 必须显式渲染；生产 443 渲染拒绝测试端口 9500。CSP 的 connect-src、form-action、script-src 保持 self。
2. 删除吞错的退出 fetch，恢复原生 POST + CSRF 和 /team 基址。浏览器用真实输入、点击、刷新，详情动态取自检索结果；303 按 requestId/hop 归属。旧 Cookie 仅内存重放，只有显式匿名或精确 SessionExpiredException 算失效。
3. 资产代理原来只连 DNS 首地址，本机 IPv6 首地址超时而 IPv4 可达。现全部候选先过原有 SSRF 校验，任一私网候选仍整域拒绝；IPv4 优先、仅网络错误有限回退，TLS/SNI、重定向拒绝和大小上限不变。连接、握手及每次读取受总计 20 秒预算约束。
4. 同轮 results、summary、退出码和哈希严格一致；latest-run 完整后原子发布。检查器拒绝 fail/blocked 计数上的假通过；浏览器 stdout 与文件完整 JSON 等值，敏感字段清洗本身会导致失败。bore 控制/公开端口必须由本轮服务实际监听后才开始业务断言；未知传输失败不能当匿名。
5. 测试更新使用明确 test-only Ed25519 身份，合成 APK 不可安装、不属于生产信任。私钥已放隔离 WSL 原生文件系统，最终实测权限 0600；Git 中只有生成器和测试，无私钥。
6. 隔离 Chrome 缺 CJK 字库已用官方 Ubuntu Noto 包私有解包解决，未安装系统包或修改全局字体。来源、大小和 SHA256 已双重核对并登记在[字体来源](../registry/bore-p2-fonts-20261027.json)。

## 历史失败与旧口径

旧 2026-10-26 的 77/0 不满足原验收要求（自 fetch 替代 UI、额外 CSP origin、零签名、summary 缺状态），不再作为完整通过依据。旧快照及独立 Codex 审计保持原样。

本轮首个 [run.UbUJ19](../../local/build/bore-p2-20261026/runs/run.UbUJ19/summary.json) 为 122/3，真实根因是 asset 504，另两项是类型连带与 runner 退出派生；这些历史结果仍保留 fail。随后 [run.HaMOXj](../../local/build/bore-p2-20261026/runs/run.HaMOXj/summary.json) 暴露 bore 启动失败却被误报 ready，已增加自有监听就绪检查并在最终轮通过。

## 快照与检查

新不可变源清单：[source-server-p2-evidence-hardened-20261027.json](../registry/source-server-p2-evidence-hardened-20261027.json)；旧 final3 不改写。最终仓库检查：python tools/repo_check.py：PASS，52项检查、0错误、exit 0；git diff --check exit 0。既有 production-py312-rebuild 尚未构建，完整离线闭合未建立；全量payload校验未执行，新字体载荷已独立核对官方SHA256。

## 生产边界

[内网只读记录](production-intranet-readonly-20261027.json)：磁盘 manifest 为 19.0.1.0.0，数据库安装版本未查；生产 Nginx 1.18.0 不支持 proxy_cookie_flags，本地 1.30.6 不能作为线上版本。候选 CSP/XFO/Referrer/默认拒绝尚未部署。内网可达不是公网或标准 443 证明。nginx -t 因非特权访问日志/证书返回 1，未以该命令建立生产配置有效性。

下一阶段若部署，需独立授权、生产运行时兼容方案与回滚点；本轮没有部署或回滚动作。客户端/EDA 旧调用迁移、写业务 UI、真机更新安装与公网验收未在本轮完成。

## 资料

已使用 find-skills 调研并核对 [Anthropic webapp-testing](https://github.com/anthropics/skills/tree/main/skills/webapp-testing) 的真实交互方法，未安装额外工具链。参考 [Nginx proxy_set_header](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_set_header)、[MDN form-action](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/form-action)。文档不复制凭据或私钥；公开合成清单和公钥证据按测试产物保留，临时会话缓冲已清理。
