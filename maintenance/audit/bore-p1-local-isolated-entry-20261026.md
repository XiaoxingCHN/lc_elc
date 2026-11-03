# bore P1 本地隔离入口 · 审计（2026-10-26）

状态：**本地隔离实现与验证完成**；真实公网节点/标准 443/真实 Odoo 会话/自动续期/生产部署**未验证**，不构成公网开放授权。
本轮未访问生产、未 SSH、未改生产配置/DNS/网络/计划任务，未卸载或清库。

## 1. 上游研究与选型

| 组件 | 版本/许可 | 结论 |
|---|---|---|
| bore | 0.5.3，**MIT**（ekzhang/bore） | 官方源码 **无 PROXY protocol**（main 分支 29 文件，README 无该选项）→ 单靠 bore 无法保留访客 IP（实测隧道后上游只见 127.0.0.1） |
| Nginx | 1.18.0（Ubuntu 包，本地非 root 解包） | 用 **stream proxy_protocol** 在受控边缘生成来源头；入口用 `listen ssl proxy_protocol` + `real_ip_header proxy_protocol` 信任边缘 |
| OpenSSL | 3.0.2 | 本地合成 CA/证书（仅 local/，Git 忽略） |

备选（未采用、未验证）：frp 的 proxy_protocol、Cloudflare Tunnel + CF-Connecting-IP。理由：均需额外账号/网络条件，且本轮不得选择或注册付费资源。

## 2. 交付文件（server/ubuntu22.04/bore）

| 文件 | 说明 |
|---|---|
| `nginx/bore-public-allowlist.conf.template` | 默认拒绝；精确路径/方法白名单；认证端点清 DB 头；`@RATE_LIMIT@` 钩子 |
| `nginx/bore-proxy-headers.conf` | X-Forwarded-For/Real-IP **覆盖**为已验证来源；Forwarded 清空；DB 头占位 |
| `nginx/bore-edge-stream.conf.template` | 受控边缘 stream 片段 |
| `scripts/verify-local-entry.sh` | 本地一键验证（真实 Nginx + bore + 合成上游） |
| `tests/test_config_contract.py` | 模板契约测试 |
| `tests/synthetic_upstream.py` | 合成上游（**不是 Odoo**，仅代理/路由边界） |
| `README.md` | 架构、许可、边界、复现 |

## 3. 真实链路（本轮实测）

```
访客 127.0.0.3 / 127.0.0.6
  --TLS--> 公开边缘 Nginx stream (127.0.0.1:9500；不接受客户端 PROXY；proxy_protocol on)
  --PROXY--> bore server (127.0.0.1:7835) --> bore client
  --> 入口 Nginx (127.0.0.1:8443；TLS + proxy_protocol；set_real_ip_from 127.0.0.1)
  --> 合成上游 (127.0.0.1:9000)
```

## 4. 测试结果

- 契约测试：`python3 -m unittest discover -s server/ubuntu22.04/bore/tests -p test_config_contract.py`
  → **Ran 9 tests, OK**，exit 0。
- 本地链路：`NGINX_BIN=… MODULE_SO=… BORE_BIN=… bash server/ubuntu22.04/bore/scripts/verify-local-entry.sh`
  → **PASS=94 FAIL=0，exit 0**（`local/build/bore-p1-20261026/run-console.log`、`run/results.jsonl`、`run/summary.json`）。
- 环境：WSL2 Ubuntu 22.04 / nginx 1.18.0 / bore-cli 0.5.3 / OpenSSL 3.0.2 / Python 3.10.12。

断言覆盖（均为真实 Nginx/bore 运行，不是 mock 断言）：

| 类别 | 数量/要点 |
|---|---|
| 配置语法与监听 | 入口/边缘两份配置 `nginx -t` 通过；上游/监听就绪 |
| Host | 正常 Host 200；带端口 Host 200；非本域 Host **444（连接关闭，curl rc≠0）** |
| 允许端点（依据真实源码） | GET /、/login、/team、/team/、/team/login、/lab、/team/lab、/lab/items/<key>（含编码冒号）、静态、asset、更新清单；POST /login、/team/login、/team/logout、/logout、会话三端点、/api/team/session、/lab/api/catalog/{search,detail,categories,facets} |
| 方法不匹配 | 5 类 → **403**（`limit_except deny` 实际语义） |
| 默认拒绝 | 10 条敏感路径 → **404 且上游 0 请求** |
| 路径绕过（--path-as-is 原样发送） | 7 条（../、//、%77eb、尾斜杠、%2F、多段 key、深层遍历）→ **404 且上游 0 请求** |
| 头覆盖 | 伪造 XFF/X-Real-IP/Forwarded → 上游只看到真实 127.0.0.1；Forwarded 为空 |
| DB 头 | 页面请求带合成库头；认证端点 **清空** X-Odoo-Database（冷会话兼容） |
| bore 隧道（无 PROXY） | TLS 200；上游来源变为 127.0.0.1 → **证明必须由边缘补 PROXY** |
| 完整链路 | 127.0.0.3 与 127.0.0.6 均 200，上游分别看到对应来源（**两来源不互相误封**） |
| 失败关闭 | 直接访问入口（无 PROXY）握手失败且上游 0；伪造 PROXY 前缀到公开边缘被忽略且上游 0；隧道断开请求失败且上游 0 |
| 限速 | A(127.0.0.5) 第 2 次 **503**；B(127.0.0.6) 仍 200；A 伪造 XFF 仍 503（key=$remote_addr） |

## 4.1 审查后修正（最终版证据）

| 审查项 | 修正与最终证据 |
|---|---|
| 正式边缘模板自相矛盾 | «nginx/bore-edge-stream.conf.template» 改为**公开 listen 无 proxy_protocol**、下游 «proxy_protocol on»；脚本**渲染并使用该模板**（不再 inline 复制）；契约测试断言公开 listen 不得含 proxy_protocol |
| 直接访问入口拒绝证据 | 改为正确 SNI/CA：«--resolve team.l-creation.club:8443:127.0.0.1 --cacert … https://team.l-creation.club:8443/team»；要求 curl rc≠0 **且** 入口 error.log 出现 «broken header … while reading PROXY protocol» **且** 上游 0 请求 |
| 伪造 PROXY 前缀 | 新增 «tests/forged_proxy_client.py»：先从公开边缘发送伪造 PROXY 行，再用受信 CA + 正确 SNI 完成 TLS/HTTP 尝试；结果被拒（握手失败），入口日志记录该伪造行，上游 0 请求 |
| 伪造 XFF/Forwarded/X-Real-IP | 完整链路请求附带伪造头；上游只看到真实来源（127.0.0.3），伪造值不出现 |
| 运行目录与进程清理 | 每次运行使用**唯一新目录**（«runs/run.XXXXXX»），WORK 已存在则拒绝；启动前检查端口占用；Nginx 启动后校验 pid 属于本次前缀；清理只针对本次记录且 cmdline 含本次目录的进程 |
| 失败证据 JSON | 结果行由 Python «json.dumps» 生成，多行错误不再破坏 JSON；缺依赖/启动失败写 summary 并以 exit 3 标记 blocked |

最终计数：主链路 **PASS=94 FAIL=0（连续两次复跑均一致）**；失败路径 **PASS=10 FAIL=0**；契约测试 **9 项 OK**。
最终复跑命令（环境变量按实际二进制路径替换）：

```bash
NGINX_BIN=<nginx> MODULE_SO=<ngx_stream_module.so> BORE_BIN=<bore> \
  bash server/ubuntu22.04/bore/scripts/verify-local-entry.sh
```

## 4.2 失败路径与运行时来源

### 失败路径测试（`tests/test_failure_paths.sh`，本轮新增）

| 断言 | 结果 |
|---|---|
| 占用 bore 控制端口 7835 的“已有服务”启动 | PASS |
| 端口被占用时脚本 blocked（exit 3）且指出 7835 | PASS |
| WORK 已存在时拒绝运行（exit 4） | PASS |
| 已占用服务不受影响（PID starttime 一致） | PASS |
| 失败分支无遗留子进程（无 nginx/bore/上游残留） | PASS |
| 释放 dummy 后端口可复用 | PASS |

合计 **PASS=10 FAIL=0**；说明失败路径不会影响已有服务，也不会留下本任务子进程。

### 进程清理语义（逐条修正）

- 每个本次启动的进程记录 **PID + /proc starttime + 身份**（nginx/bore/python3）；
  仅当三者一致才 kill，随后 TERM→等待→必要时 KILL→`wait` 回收；**不要求命令行包含 WORK**。
- 端口预检包含 **7835**，并对每个端口做最多 5 秒的等待（容忍上一轮刚退出），仍占用则 blocked。
- 每次运行使用唯一新目录（`local/build/bore-p1-20261026/runs/run.XXXXXX`），`WORK` 已存在直接拒绝。

### 运行时来源登记（local 载荷不丢来源）

- `local/build/bore-p1-20261026/runtime/PROVENANCE.json`：bore 0.5.3（MIT）、nginx 1.18.0-6ubuntu14.21（BSD-2-Clause）等
  下载 URL、版本、许可与 SHA256。
- `server/ubuntu22.04/bore/scripts/fetch-runtime.sh`：可重复下载并校验；`--verify-only` 实测 **ok=8 bad=0**。
- `maintenance/registry/payloads.json` 已登记 `bore-p1-local-runtime`（指向 PROVENANCE 及其 SHA256）。

## 4.3 运行时完整性（本轮新增）

`tests/test_fetch_integrity.sh` → **PASS=10 FAIL=0**：

- 篡改 `nginx-core` 归档后运行 fetch：**非零退出**、输出 `HASH-MISMATCH nginx-core`，且 **root/ 与 bore 均未生成**（校验先于解包）。
- `--verify-only` 对篡改归档同样非零退出。
- 正确归档 + 非法 `zzz-decoy.deb` 混入：**运行成功**（证明只解包清单内 4 个已校验 deb，不使用 `*.deb` 通配），3 个产物哈希校验通过。
- `fetch-runtime.sh` 现先校验 5 个归档（缺失/哈希不符→立即退出、不解包），解包后校验 3 个产物固定哈希。

入参路径：verify/failure 脚本自动把 `NGINX_BIN/MODULE_SO/BORE_BIN` 转绝对路径；文档示例统一用 `$(pwd)`。

## 4.4 独立复验（不覆盖）

Codex 独立复跑结果（保留其日志，本任务不覆盖）：
`local/build/bore-dsh-resume-20261026/codex-chain.log`（94/0）、`codex-failure-paths.log`（10/0）、Windows 契约 9/0。

## 5. 关键安全设计

- 入口 Nginx 只绑定**回环**，只有 bore client 对端（127.0.0.1）可注入 PROXY；`set_real_ip_from 127.0.0.1`。
- 公开边缘 **不接收**客户端 PROXY（listen 无 proxy_protocol），只主动生成；客户端伪造 PROXY 前缀成为 TLS 垃圾 → 握手失败，上游零请求。
- XFF/Forwarded 一律覆盖/清空，客户端无法自证来源。
- 动态 item key 使用正则 `^/(?:team/)?lab/items/[^/]+$`，与 Odoo `<string:item_key>` 单段语义一致。
- 合成 DB 名为 `bore_p1_synth_db`，不含生产库名。

## 6. 未验证 / 阻塞（不声称 P1 完成公网验收）

1. 真实公网节点与**标准 443**（免费/受控节点、带宽、稳定性、真实访客拓扑）未落实。
2. 真实 Odoo 会话/权限/库存（本轮为合成上游；不能替代 P2 真实实例验证）。
3. 限速与 Odoo 自身登录冷却的一致性：Odoo 计数据 `remote_addr` 且 workers 间不共享，本机限速只覆盖 Nginx 层。
4. 证书自动续期、生产部署、DNS/网络变更均未做。
5. EDA `/odoo/action-*` 与 Flutter `search_read` 旧调用迁移未做（P4）。
6. 真实移动端/VPN 跨网未测。

## 6.1 冻结

- 最终 server 源快照：`maintenance/registry/source-server-bore-p1-local-final-20261026.json`
  （**185 文件**，tree `483a1e8bcf3e3e744a14efb6588915ffe569e9989922f7437c011e4fa61f306f`，已 --activate）。
- 旧 manifest 未改写；任务中途快照 `…-local-20261026.json`（183 文件）被最终快照取代并保留。
- `python tools/repo_check.py` → **PASS，50 检查，0 错误**；`git diff --check` → exit 0。

## 7. 复现

```bash
python3 -m unittest discover -s server/ubuntu22.04/bore/tests -p test_config_contract.py
NGINX_BIN=/path/nginx MODULE_SO=/path/ngx_stream_module.so BORE_BIN=/path/bore \
  bash server/ubuntu22.04/bore/scripts/verify-local-entry.sh
```

证据目录 `local/build/bore-p1-20261026/`（Git 忽略；证书/日志/结果仅本地）。
