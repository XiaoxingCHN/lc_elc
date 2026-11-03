# 维护交接：2026-11-03 P3 Web 生产部署（r3 → 生产 LcHardwareHouse，公网回归通过）

## 用户目标与已确认边界

- 目标：把 r3 冻结候选在 2026-11-03 维护窗口部署到生产主机 192.168.31.105（DB `LcHardwareHouse`），完成模块换码与 `-u lab_team_web` 升级、网关 allowlist 切换，并做只读验收与公网回归。
- 边界（本轮实际遵守）：只改本项目 `/opt/odoo/custom-addons` 下模块、本次备份与源码快照、`/var/lib/lc-elc-bore/releases/p3-web-20261103T002651Z` 发布目录、`/etc/nginx/conf.d/lc-bore-netlify.conf` 这一个 include 文件、odoo.service/nginx.service 的启停与 reload。
- 明确未做：未 commit / 未 push；未建或发布客户端包（客户端 `1.1.3+6` 不变）；未做真实业务写入（部署后只有只读验收）；未动 DNS / Docker / 其他服务 / 其他库；未执行回滚；未读 CI。
- 凭据：sudo 口令只在 SSH stdin 中送入，不进 argv/env/日志/仓库；本机 DPAPI blob `local/private/web-ui-20261102.dpapi` 部署后已删除（`BLOB_DELETED`），本机不再存生产口令。
- 事实来源：本轮生产实测。本文件所有数字均为实测值，未四舍五入、未推算。

## 当前权威源码、分支和版本

- 分支 `codex/receipt-search-feedback`，基线 commit `b3bcbf244e44939c6d481e3f97f11579cdf9ee99`；**仍未 commit / push**。
- 冻结 r3：`maintenance/registry/source-server-web-ui-20261102-r3.json`，**258 文件**，tree `95baea916fbe4c8504e9a3bc2ce1c18235cf53689373d323b32d914d1e1fe8de`，清单 sha256 `2192a3545ebbe2ea3293072d1cc971a8deab1e524a4e39c20503d760888a7224`（本轮未改写任何冻结清单）。
- 版本：`lab_team_web 19.0.1.1.0 → 19.0.1.2.0`（生产 DB 已生效）；运维 `server-ops 2026.11.02.1`；`lab_workflow 19.0.2.0.0`、`lab_catalog 19.0.2.0.5`、`lab_inventory 19.0.1.0.0` 未变；客户端 `1.1.3+6`、EDA `3.0.3` 不变。
- 生产运行面（实测）：Odoo19，`/opt/odoo/odoo-19/odoo-bin`，`/opt/odoo/venv/bin/python3`（**Python 3.12.15**），`/etc/odoo.conf`，`/opt/odoo/custom-addons`，data_dir `/opt/odoo/.local/share/Odoo`，DB `LcHardwareHouse`，`base 19.0.1.3`，已装 **55** 个模块；nginx 1.18.0。

## 已完成工作与实际证据

### 时间线与标识戳（UTC，取自实际路径名）

- 部署落于 **2026-11-03 00:16–00:36Z**，终态 `DEPLOY_COMPLETED_UTC=20261103T003543Z`（close log `/var/tmp/lc-deploy/close-20261103T003543Z.log`）。
- 各步骤标识戳：备份标签 `…-p3-web-20261103T000658Z`、备份目录 `20261103T001648Z-p3-web-20261103T000658Z`、run env `run-20261103T001600Z.env`、网关 release `p3-web-20261103T002651Z`、验收 `verify-20261103T003528Z`、收口 `20261103T003543Z`。

### 一致备份与回滚点

- 备份目录 `/opt/odoo/backups/20261103T001648Z-p3-web-20261103T000658Z/`：`db.dump` **110,944,415 B**，sha256 `40c76d0679d2a7915ba5857d5009c291c18f17fdf239803a484246228993ba19`；`filestore.tar.gz` **12,819,190 B**，sha256 `305b841f50f0b3417b120a3ff0b52e61800d533f3a2337418f3114a2d85abfda`（**611 条目**）；`MANIFEST.json`、`odoo.log.tail` 同目录。
- 一致性判据（停服态备份）：`store_fname` distinct **139** / tar 成员 **140** / 缺失 **0**；`service_was_active=false`（即 dump 前服务确实已停，非运行态备份）。
- 源码回滚快照：`/opt/odoo/backups/module-source-before-20261103T000658Z/{lab_site,lab_team_web,lab_theme}`（仅这三个被换入模块的旧源码）。

### 换码与模块升级

- `LC_DEPLOY_MODULES=lab_site,lab_team_web,lab_theme`：`lab_site` 只做权限归一（内容 = 冻结内容）、`lab_theme` 仅由 `deploy-theme.sh` 换成冻结版；实际 `-u` 只有 `lab_team_web`。
- `lab_team_web`：`19.0.1.1.0 → 19.0.1.2.0`；`lab_workflow 19.0.2.0.0` / `lab_catalog 19.0.2.0.5` / `lab_inventory 19.0.1.0.0` 未变。
- 升级结果：`UPGRADE_EXIT=0`，错误行 **0**。

### 菜单（改指可逆性验收）

- 部署前：**234 行**（其中 lab_* **21 行**），sha256 `3eb392d032ae1c0ed7a78456cd837c89aa1dc9f7ffc3f167c2e211b24a5e7c2a`。
- 部署后比对：`removed=0`、`added=1`、`changed=12`、`match=1`；新增行 `lab_team_web.menu_legacy_label_wizard`（id 382，parent `lab_workflow.menu_lab_config`，action `lab_workflow.action_lab_label_open`）；12 条 changed **仅 action 字段变化**（即旧入口改指）；菜单树结构稳定，tree stable sha256 `bafa905fc5f5fdb65fe3ea72af42647e78300b685d5323b9764db26e9ec64b8c`。

### 网关

- release 目录：`/var/lib/lc-elc-bore/releases/p3-web-20261103T002651Z`；`/etc/nginx/conf.d/lc-bore-netlify.conf` 现 include 该 release 的 `gateway.conf`。
- include 文件 sha256：现 **`34289f2612c9adb460c787c6765f72525bd1db5359eff515164cbb1ab42508ef`**；切换前 **`bb3164e5630cc70cb24e9a1f95bdf8b5e40492ddee721c5ec5d01de2f2d8c4e9`**（回滚点 `<release>/rollback/project-include.before`，与基线同 sha）。
- allowlist：pages **24** / apis **5** / legacy **13**；nginx **1.18.0**；未动 `lc-bore-public.conf`、DNS、Docker、其他服务。

### 50-verify（只读验收）

- **PASS：129 项检查、0 失败**；`/var/tmp/lc-deploy/verify-20261103T003528Z.json` 与 `verify-facts-…env`。
- 三模块逐文件与冻结清单逐字节相等：`lab_site 19` / `lab_team_web 58` / `lab_theme 6` 文件。
- 13 条 legacy action：GET/HEAD 全部可过，POST 全部被拒；`/web/login`、`/database`、`/jsonrpc`、ORM 路径 404。
- 公网探针通过；`workflow_core.js` sha256 `6942f733fddaf4b3183a0251ad5d2ac99913d4c339921ca48dc59b7346cc0936`。

### 90-close（终态）

- `DEPLOY_STATE=completed`，`DEPLOY_COMPLETED_UTC=20261103T003543Z`，`DEPLOY_FACTS_PROVEN=43`。
- run env `/var/tmp/lc-deploy/run-20261103T001600Z.env`，sha256 `20f5b3fe34c2ed6c1c3f35a6141368a729a4e3baf4532ccdafe5dfb7905ec008`。
- close 后现场：odoo.service **active**，HTTP `/web/login` **200**。

### 公网回归（team.l-creation.club，链路 Netlify → bore → 网关）

| 路径 / 方法 | 结果 |
| --- | --- |
| `/` | 200 |
| `/login` | 200 |
| `/team/login` | 200 |
| `/team/lab/receipts` | 303 |
| `/team/scan` | 303 |
| `/lab/bags` | 303 |
| `/odoo/action-lab_workflow.action_lab_scan_console` | 303 |
| `/odoo/action-lab_inventory.action_lab_mapping` | 303 |
| `/web/login` | 404 |
| `GET /lab/api/inventory/bags` | 403 |
| `POST /team/lab/receipts` | 403 |
| `POST /lab/api/catalog/search` | 415 |
| `workflow_core.js` | sha256 与冻结一致 |
| `pages/receipts.js` | 200 |
| `workflow_receipt.css` | 200 |

结论：P3 页面与旧入口改指在公网可见；只读页面对写方法（403）、只写接口对读方法（403/415）、`/web/login` 仍被封（404），暴露面未扩大。

### 部署期修复的脚本缺陷（真实、已修，均在本地 scripts/ 内）

| 文件 | sha256 | 缺陷与修法 |
| --- | --- | --- |
| `05-bootstrap.sh` | `f2d46931a5ddf15d430f63c469f78476345a22aa20be367526301e70b6755fde` | tar 选项顺序错误；mawk 转义斜杠正则；`members.txt` 误判顶层 |
| `00-preflight.sh` | `c48bbfddb5070f35e7724761b7a865ed3e0ab7a32d2abb1385b88577bd8ef99a` | 网关 include 闸门改为声明式判定 |
| `lib.sh` | `d5da44ed05aa46fab3e90bf53fe2215bbc490c1bbff315b63445db261817ba98` | `http_login_code` 支持多路径 + `X-Odoo-Database` 头 |
| `40-gateway.py` | `487283ee6ee844a0ca81af66f57cda70fcc1a74579bb506be2096125cb231e7b` | apply 后 reload 优雅切换存在竞态，加有界 settle |
| `50-verify.py` | `14d4c1e084691486c5b231028848a553b948f269aae802c5238ee55a64997f0d` | `ir_ui_menu.action` 的 Char 与 res_id int 比较；origin 探针补 DB 头；公网 5xx 有界重试 |

`FROZEN-20261102.sha256` 已同步修后脚本；`check-scripts` = `SYNTAX_ERRORS=0`、`USED_BUT_MISSING none`。

### 最终部署包与中间包（必须区分）

- **最终实际部署包** `deploy-bundle-web-ui-20261102-r3.tar.gz`：**93,486 B**，sha256 `34a485101b3a1725e45375a1b97cf94079a80414166dc2ff24c4cc726824f67a`，**27 条目**，FROZEN **18** 条，shipped **15**，`bundle-meta` 的 freeze sha256 `f0dce4080e6170587bbda6e3836ab4f88c62ded4e7ef0dc5c76bbeff5e21401b`。
- 历史中间包（**非最终，不得部署/不得当最终值引用**）：91,307 B / `8215a795…`、91,586 B / `e453db43…`、92,857 B / `085945a2…`。

### 证据归档

- `local/web-ui-implementation/evidence/production/p3-deploy-evidence-20261103.tar.gz`：**21,344 B**，sha256 `53433008c3bb6ae48da899105e64d2fd6e814b24a47d5b2617a3fe9cdc8069b5`，**20 条目**（Git 排除目录）。
- 服务器侧证据：`/var/tmp/lc-deploy/`（run env、verify JSON、close log）。

## 剩余工作与阻塞

- 未 commit / 未 push：分支 `codex/receipt-search-feedback` 仍停在工作区（用户本轮明确不提交）。
- 客户端包未建、未发布：`1.1.3+6` 不变，无签名 APK 产物。
- 未做真实业务写：部署后只有只读验收与公网只读回归，业务写入路径未在生产走过（判断完成的方法：以真实业务单据 + 库存不变量对账）。
- 未执行回滚：回滚点与脚本均在位，但本轮未演练；判断可用性的方法是在维护窗口内按 deploy-plan §5 执行一次受控回滚演练。
- CI 未读（未接入）。
- 运行时不等价：隔离环境 WSL `Python 3.10.12` vs 生产 `Python 3.12.15`，不声称等价；生产 cp312 离线闭包仍缺（`repo_check` 的 `production-py312-rebuild` warning 保留）。
- 无签名公证书：r3 为纯源码候选，`signing.status=not_applicable`（非可执行发布物），本条不是缺陷但不得声称已签名。

## 依赖和产物

- 登记（仓库内）：`maintenance/registry/source-server-web-ui-20261102-r3.json`（258 文件 / `95baea91…` / `2192a354…`）与 `maintenance/registry/artifact-server-web-ui-20261102-r3.json`（deploy_bundle 已更新为 93,486 B / `34a48510…`，`production_deployed=true`，含 `production_deployment` 块）。
- 本机产物（Git 排除）：源码候选 ZIP `local/build/web-ui-20261102/candidates/server-web-ui-20261102-r3-source.zip`（13,251,571 B / `3800e2a2…` / 259 条目）；最终部署包同目录 `deploy-bundle-web-ui-20261102-r3.tar.gz`（93,486 B / `34a48510…`）。
- 取用命令：`python tools/release.py` 只用于生成/核对冻结清单，**不要**用它覆盖 r3 或旧清单；部署包用 `python local/web-ui-implementation/scripts/pack-bundle.py --params …` 重新打包会得到新 hash，勿覆盖最终包。
- 凭据与私钥：仅私有位置 `local/private`（本轮 DPAPI blob 已删）；不在仓库、不读内容。

## 生产状态和回滚

- **本轮确实碰过生产**（部署 + 升级 + 网关切换 + 服务启停），授权范围见首节；终态 `DEPLOY_STATE=completed`（`20261103T003543Z`）、`DEPLOY_FACTS_PROVEN=43`、服务 active、HTTP login 200；公网回归全项通过。
- 备份：`/opt/odoo/backups/20261103T001648Z-p3-web-20261103T000658Z/`（`db.dump 110,944,415 B / 40c76d06…`、`filestore.tar.gz 12,819,190 B / 305b841f…`（611 条目）、`MANIFEST.json`、`odoo.log.tail`），停服态一致备份（`service_was_active=false`，`store_fname 139/140/缺失 0`）。
- 回滚点：源码 `/opt/odoo/backups/module-source-before-20261103T000658Z/{lab_site,lab_team_web,lab_theme}`；网关 `/var/lib/lc-elc-bore/releases/p3-web-20261103T002651Z/rollback/project-include.before`（基线 include sha `bb3164e5…`，当前 `34289f26…`）；DB+附件回滚用上述一致备份。
- 恢复注意：`90-rollback.sh` 第一步先停服并证明 inactive，之后才动文件/DB；升级后到回滚时刻之间的业务写入会丢失（只留在 restore 工具的 pre-restore 备份里）；`odoo_restore.py` 只解 `filestore.tar.gz`，本次备份 tar 自洽，不受历史 supplement 缺陷影响；网关单独撤回用 `40-gateway.py --restore`，不动 DB。

## 部署后硬化与证据（硬化未部署）

- 仓库内证据：`maintenance/audit/p3-production-verify-20261103.json`（50-verify 原始输出，129 项检查全 `ok=true`）；过程与数字汇总 `maintenance/audit/p3-production-deploy-20261103.md`。
- 部署后独立只读审计（未接触生产/凭据）发现 5 处脚本缺口并已修：M1 `40-gateway.py` 增加 `nginx -T` 确认与 `.conf` 后缀校验；M2 `lib.sh need()` 遍历全部参数；M3 登录探针改用 `LC_CANONICAL_HOST` 且 `LC_DB` 空值显式报错；M4 `restore()` 失败不再写回新配置、输出 `restore-failed` 并非 0；M5 `pack-bundle.py` 默认拒绝覆盖已有包。
- 新冻结清单 `local/web-ui-implementation/scripts/FROZEN-20261103.sha256`（27 条，清单 sha256 `8ed70f4ca1723c1ff6144374708a162eded32c5891d8a54937aa03e2d323b765`），旧 `FROZEN-20261102.sha256` 原样保留。硬化后自测包 `local/build/web-ui-20261102/candidates/lc-selftest-hardening-20261103.tar.gz`（96,161 B / `7ac817dc…`）经 WSL 无特权 bootstrap 演练到 `FROZEN_SHIPPED_ENTRIES=15`、`BUNDLE_META_OK=1`，仅在沙箱 `mkdir /home/hbut` 处预期失败。
- **这些硬化脚本尚未部署**；生产当前运行的是最终部署包（`34a48510…`）内的脚本。下次部署必须重新 pack（`pack-bundle.py` 会取最新 FROZEN 并拒绝覆盖）。
