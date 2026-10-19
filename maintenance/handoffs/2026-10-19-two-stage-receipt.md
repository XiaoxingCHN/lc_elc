# 维护交接：2026-10-19 两阶段入库候选

## 用户目标与已确认边界

按已确认计划，实现先批量建档制袋码、打印贴标，再逐袋扫码选择库位确认实际入库。采用 apple-ui-designer 设计和 apple-design 审查。用户要求节省交互与 token，本轮单代理实施。仅本地开发、测试和候选源冻结，没有生产授权或生产操作。

## 当前权威源码、分支和版本

- 分支：codex/two-stage-receipt-plan；起始 commit：28dd8bf032404eee5d1196aff786fd96b2cf8b52，尚未提交或推送。
- 客户端唯一源 clients/app：1.1.0+3 开发候选；lab_workflow：19.0.1.1.0 开发候选。其他模块及 EDA 版本不变。
- 新增并激活 maintenance/registry/source-client-two-stage-receipt-20261019.json 与 source-server-two-stage-receipt-20261019.json。旧源清单、成品和发布关联未覆盖。
- 本轮没有新安装包，历史发布客户端仍为 1.0.1+2；生产模块版本沿用原记录。

## 已完成工作与实际证据

实现和契约见 docs/development/TWO_STAGE_RECEIPT_IMPLEMENTATION.md；任务单见 maintenance/tasks/2026-10-19-two-stage-receipt.md。

已实现：独立待入库记录与统一袋码唯一登记；手工／资料库建档；待打印选择恢复；待入库标签、稳定字段与关键参数；取消和补打；扫码与同料号／同类库位推荐；确认事务、防重、权限、公司及会话隔离；真实仓库入口与器件详情入口。原直接入库接口保持兼容。

本轮实际验证（不是历史归档结果）：

| 检查 | 环境、命令及退出码 | 实际结果 |
|---|---|---|
| Flutter 全量回归 | Windows，Flutter 3.47.7 / Dart 3.13.5；通过缓存 SDK 的 Dart 执行 flutter_tools.snapshot test --no-pub --reporter expanded；exit 0 | 242 通过、5 跳过；含新增 9 项队列、幂等、缩放和界面用例 |
| Dart 静态检查 | dart analyze lib；exit 0 | 无 error/warning；仍有现有及 API 弃用级 info，详见日志 |
| 服务端纯逻辑 | Python 3.12.14 运行 lab_workflow/tests/test_offline_logic.py；exit 0 | 收集 28 项，27 通过、1 跳过（未安装可选 qrcode 交叉核验库） |
| Odoo ORM 与接口基础 | WSL，Odoo 19 / Python 3.10 / PostgreSQL 14；命名空间隔离新库；run_isolation_tests.sh --keep --with-http --skip-process-concurrency --real-catalog 当前 addons 目录；exit 0 | 收集 54 项，53 通过、1 跳过（原 HttpCase 依赖回滚后的测试账号）；安装、更新及新 pending 标签 PDF 实际执行 |
| HTTP 并发 | 上述隔离运行器启动普通 HTTP 服务，独立登录会话与 Barrier；exit 0 | 6 场景通过，含两设备重复制袋及不同请求同时确认同袋；同时验证旧领用／归还／直接入库 |
| 路由 | python tools/generate_routes.py --check；exit 0 | 30 条注册项一致 |
| 文档、源码与 Git 边界 | python tools/repo_check.py --output maintenance/audit/two-stage-receipt-repo-check.json；git diff --check；均 exit 0 | 49 项检查通过，保留既有 cp312 载荷未完成警告；完整大文件 hash 未重测 |

运行 Flutter 时设置项目内 PUB_CACHE 和 local/build/test-temp，抑制遥测；本机 sandbox 的回环 WebSocket 限制导致初次测试启动失败，获工具执行许可后在本机运行测试。初次 pub get 离线依赖解析完成，但插件 symlink 权限失败；未启用系统开发者模式，未把这次 pub get 标为通过。最终测试使用 --no-pub。

服务端初次 HTTP 测试被继承代理阻断，随后仅清除测试子进程的代理环境。进程内并发夹具发生测试框架锁等待，核对 PID 后只中止本轮测试进程，保留失败日志；最后显式 skipped，未算通过。真实 HTTP 路径独立通过。原归还并发夹具曾把另一个无权读取原领料的账号当作竞争者，已改为同一借用人的两个会话，并要求明确业务拒绝码；最终归还竞争结果为 1 成功、1 PRECONDITION_FAILED，未归还量 5。

日志位于 local/build/two-stage-flutter-all.log、two-stage-flutter-focused.log、two-stage-python-test.log、two-stage-analyze.log、two-stage-odoo-isolation-final.log；详细 WSL 最终日志在 /var/tmp/labwf_out.N0i4Zi，仅包含本轮临时测试材料。原生三端和生产未执行项不能由这些记录顶替。

设计审查：已查看 local/build/two-stage-ui/scan-confirm.png，修正窄屏菜单、放大文字布局、按钮尺寸、确认库位、队列可见性与跨页面标签类型残留。以语义主题色、分组和标准控件实现；测试截图不能代表实体设备的视觉／无障碍验收。

## 剩余工作与阻塞

1. 构建 Windows／Android／Linux 候选包，验证安装、升级与旧客户端接口兼容；当前只有候选源码。
2. 实机核验相机、扫码枪、扫码后的连续焦点、系统打印、纸张尺寸和标签可扫性；Linux SecretService/CUPS 等原生项保持未验证。
3. 进程内并发测试框架锁问题仍未修复，标 blocked；本轮新防重已由正常 HTTP 服务覆盖。
4. 同类推荐基于内部物料分类，不做容量判断；生产升级仍需单独授权及备份／回滚计划。

## 依赖和产物

未新增第三方依赖。Flutter 与字体沿用现有登记；截图仅测试时加载已有字体。新增源清单含完整文件 hash；本轮验证摘要和日志 SHA256 见 maintenance/audit/two-stage-receipt-validation.json。不读取或登记真实凭据、私钥、数据库或聊天日志。

## 生产状态和回滚

没有访问生产接口、部署、重启、导入、采集或库存写入。隔离测试仅操作临时库，未修改原运行时业务库。工作树未提交，可审阅差异后决定合入；候选源 active 指针可切回原 manifest，旧 manifest 不修改。尚无生产变更，无生产回滚动作。
