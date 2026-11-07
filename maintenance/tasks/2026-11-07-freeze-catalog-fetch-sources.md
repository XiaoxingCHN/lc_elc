# 任务：冻结器件库按需抓取的源码清单

- Status: done
- Category: release

- 目标/用户场景：把 2026-11-06 已交付并已部署到生产的「器件库按需抓取」（`lab_catalog 19.0.2.0.10`）连同同批客户端改动登记成不可变源码清单，使 `tools/repo_check.py` 的 `frozen-source` 错误归零，后续发布/回溯能对上是哪一版源码。
- 当前问题及复现方法：`python tools/repo_check.py` exit 1，两条错误——`frozen-source:client`（4 个文件）与 `frozen-source:server`（13 个文件）；原因是 active 清单仍是 2026-11-04/11-06 的旧快照，工作区源码已在其后改动。新文件（`lab_catalog_fetch.py`、`tools/lcsc_remote.py`、`data/lab_catalog_cron.xml` 等）不在旧清单里，所以旧检查只报“已登记文件被改动”，不报“有新增文件”。
- 验收标准：新 server/client 清单已生成并 `--activate`；`repo_check.py` exit 0、0 errors；`generate_routes.py --check` exit 0；`git diff --check` exit 0；旧清单文件未被改写；16 条既有离线载荷警告照旧记录，不声称全仓零告警。
- 允许修改目录/接口：`maintenance/registry/`（新增两份清单 + `active-sources.json` 指针）、`CHANGELOG.md`、`docs/operations/CURRENT_STATE.md`、`maintenance/HANDOFF_CURRENT.md`、`maintenance/handoffs/2026-11-06-catalog-on-demand-fetch.md`、本任务单。不改任何业务源码、不升级模块、不部署、不推送。
- 业务不变量/依赖：清单只记录源码哈希，不改运行中的服务；生产仍是 2026-11-06T14:29–14:31Z 部署的四模块版本（`lab_catalog 19.0.2.0.10` / `lab_inventory 19.0.1.1.0` / `lab_workflow 19.0.2.0.2` / `lab_team_web 19.0.1.2.1`）。
- 负责人/协作者及分工：主代理执行，用户授权在本会话完成。
- 分支/起始commit/源码manifest：分支 `feat/receipt-param-search`，起始 HEAD `aff2ea4`；激活前 active 为 `source-server-param-search-20261104-r2.json` / `source-client-liquid-glass-20261106.json`。
- 环境与凭据获取方式（只写位置，绝不写值）：本机 Python + `tools/release.py`，不需要任何生产凭据；本轮未连接服务器。
- 实施步骤：
  1. 读 `docs/development/WORKFLOW.md`、`tools/release.py`、`active-sources.json` 确认命名与激活约定。
  2. `python tools/release.py snapshot --component server --output maintenance/registry/source-server-catalog-fetch-20261106.json --activate`。
  3. `python tools/release.py snapshot --component client --output maintenance/registry/source-client-catalog-fetch-20261106.json --activate`。
  4. 重跑 `repo_check.py`、`generate_routes.py --check`、`git diff --check`。
  5. 更新文档与交接。
- 测试命令、实际结果与退出码：
  - 冻结前 `python tools/repo_check.py`：exit 1，52 项通过、**2 条错误**（`frozen-source:client` 4 文件、`frozen-source:server` 13 文件）、16 条 payload 警告。
  - 冻结后 `python tools/repo_check.py`：**exit 0，`result=PASS`，52 项通过、0 错误、16 条既有 payload 警告**（未执行 `--verify-payloads`）。
  - `python tools/generate_routes.py --check`：exit 0。
  - `git diff --check`：exit 0（仅提示 `active-sources.json` 的 CRLF 将被 Git 归一）。
- 未验证项及风险：未跑 `--verify-payloads`；清单只覆盖纳入 Git 的源码，本机排除目录（`local/`、`.tomc/`、`dependencies` 载荷等）不在其中；客户端未构建安装包，本清单不代表任何可安装产物；未推送。
- 发布文件、hash和回滚点：
  - `maintenance/registry/source-server-catalog-fetch-20261106.json`：271 文件，tree `10c3aa4ad450dfb4bd1b127777b6c5f05cc0d9fdfc51f7287845e4b41cf7757f`，文件 77,062 B，清单 sha256 `fd0870000b5372eb72f0a778aa059231866ca444708941095a0507ddece555f0`。
  - `maintenance/registry/source-client-catalog-fetch-20261106.json`：178 文件，tree `a2d5d42c5fa58ba8f07c70e5f95b831b3dc9de40b274134646955f6add70abeb`，文件 45,543 B，清单 sha256 `dd872ded69a47b849b9a2d1e506bc70e17150e0444f60cd8910f6b8dbaedf250`。
  - 回滚：把 `maintenance/registry/active-sources.json` 的 `server`/`client` 指回旧清单即可，旧清单文件未被改写。
