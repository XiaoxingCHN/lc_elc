# 交接：bore 公网入口 P1 本地隔离实现（2026-10-26）

## 结果

- 在 `server/ubuntu22.04/bore` 交付可审查、可搬迁、可重复验证的 P1 实现：默认拒绝 allowlist、头覆盖、
  边缘 stream 模板、本地验证脚本、契约测试、README。
- 本地真实链路验证 **94 断言通过 / 0 失败**；契约测试 **9 项通过**。
- 关键结论：**bore（MIT）官方不支持 PROXY protocol**，因此来源 IP 必须由**受控边缘 Nginx stream** 生成；
  组合链路（边缘 → bore → TLS+PROXY 入口 → 上游）已本地实测可用，两个来源互不误封。
- 安全项实测：非本域 Host 断开、方法不匹配 403、敏感路径 404 且上游零请求、路径绕过被拒、
  伪造 XFF/Forwarded 不获信任、直接访问入口与伪造 PROXY 失效、隧道断开失败关闭、登录端点限速生效且不可用伪造 XFF 逃逸。

## 复跑与失败路径

```bash
bash server/ubuntu22.04/bore/scripts/fetch-runtime.sh            # 下载（或 --verify-only 校验）
python3 -m unittest discover -s server/ubuntu22.04/bore/tests -p "test_config_contract.py"   # 9/0
NGINX_BIN="$(pwd)/local/build/bore-p1-20261026/runtime/root/usr/sbin/nginx" \
MODULE_SO="$(pwd)/local/build/bore-p1-20261026/runtime/root/usr/lib/nginx/modules/ngx_stream_module.so" \
BORE_BIN="$(pwd)/local/build/bore-p1-20261026/runtime/bore" \
  bash server/ubuntu22.04/bore/scripts/verify-local-entry.sh     # 94/0
# 同上环境变量：
bash server/ubuntu22.04/bore/tests/test_failure_paths.sh        # 10/0
bash server/ubuntu22.04/bore/tests/test_fetch_integrity.sh      # 10/0（篡改归档拒绝且不解包）
```

失败路径已验证：占用 7835 → blocked(exit3) 且不杀已有服务、无子进程残留；WORK 复用 → exit4。

## 未完成 / 阻塞

1. 真实公网节点与标准 443（不选择公共 bore.pub、不注册付费资源）。
2. 真实 Odoo 实例的会话/权限/库存与限速一致性（本轮合成上游，明确不能当验收）。
3. 证书自动续期、生产部署、DNS/网络变更。
4. EDA/Flutter 旧调用迁移（P4）。
5. 真实移动端/VPN 未测。

## 下一步（P2 前置）

1. Codex 审查本实现与证据；
2. 在真实 Odoo 隔离实例上复验冷会话/登录/退出/角色与限速（P2 只读灰度）；
3. 再讨论受控节点与 443 的选型（需用户资源决策）。

## 产物

- 任务：`maintenance/tasks/2026-10-26-bore-p1-local-isolated-entry.md`
- 审计：`maintenance/audit/bore-p1-local-isolated-entry-20261026.md`
- 证据：`local/build/bore-p1-20261026/`
- 源快照（最终）：`maintenance/registry/source-server-bore-p1-local-review2-20261026.json`
  （**186 文件**，tree `0455170e3cc3b677700dfa21d8020d7f27afb2a38a72724f22baca8bbd50543d`，已 --activate）。
  同任务内先后产生 183 / 185 / 186 文件三份快照（实现→审查修正→完整性修正），均保留、旧 manifest 未改写。

未改生产、未开公网、未推送 Git。

## 独立复验（保留，不覆盖）

Codex 独立复跑：链路 94/0、失败路径 10/0、Windows 契约 9/0；
日志 `local/build/bore-dsh-resume-20261026/codex-chain.log`、`codex-failure-paths.log`。

Codex 最终结论：接受 P1 本地隔离实现，仍不代表公网/生产放行。最终版独立验证 9 项契约、94 项链路、10 项失败路径、10 项归档完整性通过，仓库检查 50 项通过；详细命令、日志及未测边界见 [Codex 审查](../audit/bore-p1-codex-review-20261026.md)。用户恢复内网后由原 DSH 会话继续 P2，生产仅只读核对。
