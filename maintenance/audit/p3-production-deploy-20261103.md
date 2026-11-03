# P3 Web 生产部署与部署后硬化记录（2026-11-03）

本文件记录 2026-11-03 将 r3 源码部署到生产（192.168.31.105，Odoo 19，DB `LcHardwareHouse`）的实测结果，以及部署后独立只读审计发现的问题与硬化修正。所有数字取自服务器侧生成的 env/JSON 与本地独立复算，未含口令、cookie、token、真实 `odoo.conf` 或数据库行数据。

## 1. 时间线与结果

| UTC | 事件 |
|---|---|
| 00:16:32 | 08-window 停服，`SERVICE_STOPPED_VERIFIED=1`，窗口标记写入 |
| 00:16:48 | 10-backup 一致备份完成（停机态） |
| 00:19:40 | 15-menu-snapshot 菜单基线 234 行 / 21 条 lab |
| 00:19:56 | 30-upgrade 首跑：`-u lab_team_web` 退出 0、DB 版本已变，但探针 `HTTP_8069_LOGIN=404` 判失败并停服（缺 `X-Odoo-Database` 头） |
| 00:21:28 | 30-upgrade 重跑成功：退出 0、错误行 0、`HTTP_8069_LOGIN=200`，窗口关闭 |
| 00:26:51 | 40-gateway `--apply` 切换成功（reload 优雅切换竞态已加有界 settle） |
| 00:35:28 | 50-verify **PASS：129 项检查 / 0 失败** |
| 00:35:43 | 90-close：`DEPLOY_STATE=completed`、`DEPLOY_FACTS_PROVEN=43` |

终态（只读复核）：`odoo`、`nginx`、`lc-bore-public.service` 均 active；`lab_team_web` 19.0.1.2.0；`lab_workflow` 19.0.2.0.0；`lab_catalog` 19.0.2.0.5；`lab_inventory` 19.0.1.0.0；Odoo base 19.0.1.3；已装模块 55 个。菜单 235 行（226 生效）/ 22 条 lab：新增 1、移除 0、改指 12（仅 `action` 字段）。

## 2. 备份与回滚点

- 一致备份 `/opt/odoo/backups/20261103T001648Z-p3-web-20261103T000658Z/`：`db.dump` 110,944,415 B / sha256 `40c76d0679d2a7915ba5857d5009c291c18f17fdf239803a484246228993ba19`；`filestore.tar.gz` 12,819,190 B / sha256 `305b841f50f0b3417b120a3ff0b52e61800d533f3a2337418f3114a2d85abfda`（611 条目）；`MANIFEST.json`；`service_was_active=false`；DB 侧 `store_fname` 139、归档内 140、缺失 0。
- 源码回滚快照 `/opt/odoo/backups/module-source-before-20261103T000658Z/{lab_site,lab_team_web,lab_theme}`。
- 网关回滚点 `/var/lib/lc-elc-bore/releases/p3-web-20261103T002651Z/rollback/project-include.before`（切换前 include sha `bb3164e5630cc70cb24e9a1f95bdf8b5e40492ddee721c5ec5d01de2f2d8c4e9`）。
- 未执行 90-rollback；上述备份未做过恢复演练，属回滚依赖而非已验证回滚。

## 3. 网关

- `/etc/nginx/conf.d/lc-bore-netlify.conf` 现为 `include /var/lib/lc-elc-bore/releases/p3-web-20261103T002651Z/gateway.conf;`，include sha256 `34289f2612c9adb460c787c6765f72525bd1db5359eff515164cbb1ab42508ef`。
- 形状：pages 24 / apis 5 / legacy actions 13；上游白名单 `http://127.0.0.1:8069`；`/web/login|database|jsonrpc|ORM` 全部 404；跨源 403；写方法 403/405。
- 未动 `lc-bore-public.conf`（旧直连 vhost）、DNS、Docker 或其他业务服务。失败尝试生成的 release `p3-web-20261103T002156Z`、`p3-web-20261103T002532Z` 仍在磁盘但未被 include（惰性保留）。

## 4. 公网回归（team.l-creation.club，Netlify → bore → 网关 → 8069）

`/` 200、`/login` 200、`/team/login` 200、`/team/lab/receipts` 303、`/team/scan` 303、`/lab/bags` 303、`/odoo/action-lab_workflow.action_lab_scan_console` 303、`/odoo/action-lab_inventory.action_lab_mapping` 303；`/web/login` 404、`GET /lab/api/inventory/bags` 403、`POST /team/lab/receipts` 403、`POST /lab/api/catalog/search` 415（Odoo 拒绝无 content-type 的 POST，证明端到端可达）；`workflow_core.js` sha256 `6942f733fddaf4b3183a0251ad5d2ac99913d4c339921ca48dc59b7346cc0936` 与冻结一致，`pages/receipts.js`、`workflow_receipt.css` 均 200。

## 5. 50-verify 证据（仓库内）

`maintenance/audit/p3-production-verify-20261103.json` 为原始 50-verify 输出（129 条检查，全 `ok=true`，`checks_failed=0`，`checked_at=2026-11-03T00:35:28Z` 级）。服务器侧同源证据归档：`local/web-ui-implementation/evidence/production/p3-deploy-evidence-20261103.tar.gz` 21,344 B / sha256 `53433008c3bb6ae48da899105e64d2fd6e814b24a47d5b2617a3fe9cdc8069b5`（20 条目，Git 排除）。

## 6. 部署包与字节一致性

| 用途 | 文件 | 大小 | sha256 |
|---|---|---|---|
| **最终实际部署** | `deploy-bundle-web-ui-20261102-r3.tar.gz` | 93,486 B（27 条目 / FROZEN 18 条 / shipped 15） | `34a485101b3a1725e45375a1b97cf94079a80414166dc2ff24c4cc726824f67a` |
| 中间（50-verify 修 A） | 同路径（已被后续覆盖） | — | `59a1a16e…`（仅前缀留存） |
| 中间（50-verify 修 B） | 同路径（已被后续覆盖） | — | `174e4a03…`（仅前缀留存） |
| 中间（gateway settle） | 同路径（已被后续覆盖） | 92,857 B | `085945a2279947c45fe1d4c2804b9ba7eae5ab0b522861cc7ee4c3fb27ef6a54` |
| 中间（bootstrap 修） | 同路径（已被后续覆盖） | 91,586 B | `e453db4328d22c6df7beefecf8c4a97cd27359ba68fddfac6aa4d7f76cf11faa` |
| 中间（首轮） | 同路径（已被后续覆盖） | 91,307 B | `8215a7958fe227452f19f3458a149509169cfd3cf26fadfbd6ecad82b6e8f02d` |

**已知缺陷（部署期）**：`pack-bundle.py` 原以 `w:gz` 直接覆盖同名输出，导致上述中间包的原始字节已丢失，只剩哈希前缀记录；这违反“成品不可覆盖”。已在本轮硬化中改为默认拒绝覆盖（见 §8 M5）。

各步实际运行脚本与最终 FROZEN 的一致性：00-preflight `c48bbfdd…`、05-bootstrap `f2d46931…`、10-backup `f4d04c68…`、15-menu `c56a274d…`、20-stage `74d671e9…`、30-upgrade `3e7a2fb7…`、40-gateway `487283ee…`、lib.sh `d5da44ed…` 在成功执行时与最终部署包内字节相同；50-verify 在修复后才 PASS，PASS 那次运行的就是最终包（`14d4c1e0…`）。即“最终包内脚本 = 最终 PASS 所依赖的脚本”，中间包只对应更早的失败/中间尝试。

## 7. 部署期修复的脚本缺陷

| 脚本 | 问题 | 修复后 sha256 |
|---|---|---|
| 05-bootstrap.sh | GNU tar 长选项位置错误；mawk 拒绝转义斜杠正则；`members.txt` 落在解包目录被误判非法顶层项 | `f2d46931a5ddf15d430f63c469f78476345a22aa20be367526301e70b6755fde` |
| 00-preflight.sh | 网关 include 闸门要求全机唯一引用 releases，生产实有两个 vhost；改为参数声明 + 其它文件只报告 | `c48bbfddb5070f35e7724761b7a865ed3e0ab7a32d2abb1385b88577bd8ef99a` |
| lib.sh | 登录探针把裸 `/login` 当唯一入口且缺 `X-Odoo-Database`，导致 30-upgrade 假失败 | `d5da44ed05aa46fab3e90bf53fe2215bbc490c1bbff315b63445db261817ba98` |
| 40-gateway.py | `nginx reload` 优雅切换，探针立即执行命中旧 worker 世代 → 误判并回退；加有界 settle | `487283ee6ee844a0ca81af66f57cda70fcc1a74579bb506be2096125cb231e7b` |
| 50-verify.py | `ir_ui_menu.action`(Char "model,res_id") 与 `ir_model_data.res_id`(int) 直接比较导致 psql 失败；origin 探针缺 DB 头；公网 5xx 无重试 | `14d4c1e084691486c5b231028848a553b948f269aae802c5238ee55a64997f0d` |

## 8. 部署后独立只读审计与硬化（未部署、待下次使用）

审计结论（只读代理，未接触生产/凭据）：18/18 冻结哈希与磁盘一致、全部脚本可解析、check-scripts 通过、fail-closed 逻辑自洽；但存在以下真实缺口，已修：

- **M1 网关没有证明 nginx 加载了新 include**：`nginx -t` 只解析文件树，即使配置未 include 目标文件也能通过。已加：`validate_include_path` 强制 `.conf` 后缀 + `/etc/nginx/conf.d` 父目录 + 真实文件；`apply()` 在探针通过后跑 `nginx -T`，要求生效配置中出现本 release `gateway.conf` 且 `include` 指令恰好 1 次，否则回滚；结果 env 与 JSON 记录 `GW_NGINX_T_CONFIRM=1` / `GW_CONF_IN_NGINX_T` / `nginx_t_confirmed`。`40-gateway.py` → `186cf64c9487a49baab65d3910de796ae8ae5d8f7b59751f2767f2784189bcbd`。
- **M2 `need()` 只校验第一个参数**：改为遍历 `"$@"`，一次列出所有缺失名。`lib.sh` → `2c944639f6541b9862e6f41b6b1fa7df91b8d6d3f1f896884bd3762118f0863d`。
- **M3 登录探针硬编码 Host 并在 `LC_DB` 为空时静默回退**：改用 `LC_CANONICAL_HOST`（缺省 `team.l-creation.club`）；`LC_DB` 为空时打印错误、写 `lib-errors.log` 并 `die`。
- **M4 `40-gateway.py restore()` 失败时写回“新配置”**：改为每次从 rollback 目录重读原始字节、校验回写 sha 等于原 sha；失败输出 `status=restore-failed` + 实际内容 sha + `SystemExit(1)`，不再打印成功。
- **M5 `pack-bundle.py` 覆盖已有包**：默认拒绝并非 0 退出（打印既有 sha 与两种做法）；`--force` 时 bundle-meta 记录 `overwritten=true` + `overwritten_sha256`。`pack-bundle.py` → `26c803a47256848ea43415c1d53d18718706117a845e4c462c5ef33af99bd18a`。
- 配套：`guard_env_file` 白名单加 `GW_*`（否则 rollback/close 会拒绝新 run env 键）；`find_freeze()` 取最新清单（旧清单保留为历史）；`frozen_file()` 正确解析 `tools/`→`server/ubuntu22.04/`、`gateway_source/`→`server/ubuntu22.04/bore/`。`50-verify.py` → `75610f0f84efb604179b64a88a56234cb61b5f9aca77c93503a37be9253fd444`。

新冻结清单 `local/web-ui-implementation/scripts/FROZEN-20261103.sha256`（旧 `FROZEN-20261102.sha256` 原样保留）：27 条 = 15 随包脚本 + 3 本机脚本 + 5 `tools/*` + 4 `gateway_source/*`；清单 sha256 `8ed70f4ca1723c1ff6144374708a162eded32c5891d8a54937aa03e2d323b765`。本地独立复核：27/27 哈希一致、0 缺失。

硬化后自测包（**非部署包**，仅用于验证打包与 bootstrap 链路）：`local/build/web-ui-20261102/candidates/lc-selftest-hardening-20261103.tar.gz` 96,161 B / sha256 `7ac817dcedfb5dee32cbb47666d6be8cd297c9c7d77268a77c8fa44ad7b30f46` / 27 文件 / FROZEN `FROZEN-20261103.sha256` / shipped 15。WSL 无特权演练 `05-bootstrap.sh`：`BUNDLE_SHA256` 一致、`TOOLS_IMPORT_OK=5`、`BUNDLE_META_OK=1`、`FROZEN_SHIPPED_ENTRIES=15`，最后仅因沙箱无法 `mkdir /home/hbut` 退出（预期）。pack 覆盖拒绝已验证：exit 1 且既有文件 sha 不变。

**未验证**：`apply` 的 `nginx -T` 分支与 `restore-failed` 分支需要 root + 真实 nginx，本轮只做静态审查与 `py_compile`；`validate_include_path` 的“接受”路径（`/etc/nginx/conf.d` 下真实 `.conf`）未跑通。硬化脚本尚未部署，生产仍运行 §7 那一代（最终部署包内）脚本。

## 9. 明确未做 / 边界

- 未 commit、未 push；工作区改动仍未提交，分支 `codex/receipt-search-feedback`（基线 `b3bcbf244e44939c6d481e3f97f11579cdf9ee99`）。
- 未构建/发布客户端（客户端版本仍 1.1.3+6）。
- 未做登录态真实浏览器回归：部署后本机不再保存任何生产口令（DPAPI blob 已删除），匿名探针只证明路由/权限边界，不能证明登录后的页面交互；如需 UI 级回归需用户提供口令并另行授权。
- 未做真实业务写入、未动 DNS/Docker/其他业务服务、未卸载任何模块、未执行回滚。
- 未读取 GitHub CI 结果。
