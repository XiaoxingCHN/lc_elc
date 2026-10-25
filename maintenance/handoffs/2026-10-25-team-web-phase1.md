# 维护交接：战队仓库 Web 第一批（核心查询流程已验收，候选未上线）

## 现行结论（2026-10-25 收尾）

- 新增 `lab_team_web` **19.0.1.0.0 候选源码**，**未部署生产**。
- 最终源码复跑：L1 `Ran 66`，**65 通过 + 1 跳过**（skip 为需 Odoo 的 HTTP 模块入口），exit 0；
  隔离 Odoo 19 私有库 L2 **11/11 通过**，0 失败 0 错误，exit 0。
- Codex 浏览器验收通过本批核心范围（375px 紧凑行 / 桌面 4:3 / 筛选 / 深链接回跳 / CSRF 退出）。
  仅代表本批本地查询流程，不代表生产上线、真机、大目录或真实编辑器保存已通过。
- 私有预览实例已在验收后关闭；私有测试库与合成数据保留用于复现，未递归删除。
- 源码已用 `tools/release.py snapshot --component server --output <新唯一候选 manifest> --activate`
  冻结为**候选**；旧 manifest 与产物关联未改写。


## 关键设计（下一批勿推翻）

1. 不复用原生 WebClient 外壳；页面自渲染 + 少量渐进 JS。
2. `/` 只在"配置了 management_host + Host 命中 + 非编辑器/iframe 上下文"时接管，
   通过 `ir.http._dispatch` 短路实现，不抢注册路由；其它 Host 完全回退。
3. 编辑器识别用 `Sec-Fetch-Dest: iframe` / `Referer: /website/*` / `edit` 参数，
   **不用** `session.force_website_id`（否则管理员用过编辑器后欢迎页会一直变旧站）。
4. `_dispatch` 内返回 QWeb Response 必须手动 `flatten()`，否则 200 空 body。
5. 页面内所有 DB 读取都包 savepoint，异常在 savepoint 外捕获后渲染错误页，
   避免 InFailedSqlTransaction 导致整页白屏。
6. 目录页只要求 `lab_catalog` 读取角色；不用 `inventory/bootstrap` 的失败挡人。

## 已知缺口/风险

- 浏览器像素、窄屏、错误态由 Codex 验收；移动端未真机验证。
- 真实网站编辑器 UI（iframe 内部导航 + 保存）未点开，仅用 iframe/Referer 信号模拟通过。
- 缺 `gevent`（离线 wheelhouse 无此包），长轮询/websocket 未测；HTTP 页面不受影响。
- 分面筛选面板、两阶段入库、领用归还、标签打印未接入。
- 初期登记和来源检查错误已在收尾修正，最终 Python3.15 全仓检查 exit0、49 项通过。Python3.12 对既有 Python/ 载荷的语法检查仍失败，未删除该载荷；详情见 Codex 审查。

## 下一步建议

1. 核心浏览器验收、源快照冻结和组件登记已完成，证据见下方收尾清单。
2. 生产发布见独立任务 `2026-10-25-team-web-publish.md`，本交接保留候选收尾时点。
3. 第二批：两阶段入库 + 领用归还接线（复用既有 /lab/api/inventory/*）。


## 收尾清单（2026-10-25）

| 项 | 状态 |
|---|---|
| 当前登记 components.json | 已移除废弃 lab_portal 的源码必需路径；登记 lab_inventory/lab_catalog/lab_workflow/lab_theme/lab_site/lab_team_web 及各自版本 |
| server 候选源快照 | `source-server-team-web-phase1-20261025.json`，175 文件，tree `9a333b84b161e57e…`，已 --activate；旧 manifest 未改 |
| README / CURRENT_STATE | 已写明"候选、未上线"，并注明 lab_portal 已废弃、不再作为当前能力 |
| CHANGELOG | 已记录本批最终事实（含缓存键修复与手机紧凑行） |
| 预览实例 | 已关闭（PID/命令行/127.0.0.1:18069/私有 data 逐项核对）；私有数据保留 |
| repo_check | exit 0 / PASS，49 项，errors 空，保留 known-payload-not-built 警告；未跑 --verify-payloads |
| 生产 | 未安装 lab_team_web、未重启、未改 DNS/代理、未推送 GitHub |

## 下一批入口

1. 生产部署需另行授权（含备份、变更窗口与回滚）。
2. 第二批：两阶段入库（pending）+ 领用/归还接线，复用 `/lab/api/inventory/*`。
3. 分面筛选面板、标签打印、库位管理。
