# 维护交接：2026-10-26 bore公网安全与自有UI统一方案

## 用户目标与已确认边界

用户明确只需要Odoo一次登录，不要外加Access/SSO/验证码登录平台；希望bore提供公网通道、尽量免费且适合国内访问，并将旧Odoo页面整合为自有UI。本轮要求写完整方案，没有要求立即安装、开放公网、切DNS、卸载模块或删除数据库。原先“结构先确认，再派给DSH”的分工保留；本轮未派发。

## 当前权威源码、分支和版本

分支codex/two-stage-receipt-plan，HEAD14cf1ef44c6da1a1c1e4a77bbe51c446023a1e71。lab_team_web19.0.1.0.0，其他组件版本以maintenance/registry/components.json为准。server175文件冻结source-server-team-web-phase1-20261025.json保持不变，tree9a333b84b161e57efe161d1a81c7e7e24fd84f23888c2c70c8556cacfbae98c4。

## 已完成工作与实际证据

- 方案：docs/requirements/PUBLIC_ACCESS_AND_UNIFIED_UI_PLAN.md。明确公网入口、一次Odoo登录、全部日常页面统一、管理员仅内网维护、旧网站依赖审计、API白名单、成本/节点约束、分阶段开发、安全验收和回滚。
- 本地AST盘点38个路由装饰器（部分多别名），证据local/build/bore-own-ui-plan-20261026/routes.json；根页另由ir.http按Host接管。现有自有UI只读，入库、归还、库位、打印等要接线，不能先删旧UI让业务中断。
- EDA panel.js仍生成/odoo/action-*；Flutter products_provider.dart保留search_read，底层OdooClient通用ORM调用。公网入口收敛必须先解决兼容，不一刀切/web/*。
- 官方bore为L4中转，默认不能假定保留访客IP；本次读取Odoo19官方res_users.py确认登录失败按remote_addr计数、非跨worker共享，错误限速可能误伤全部用户。方案采用受控公网TCP入口＋成熟PROXY协议，组合验证未做、不当作已部署。
- 官方资料调研采用bore MIT、Odoo原生认证与业务模型、Nginx现有能力，避免自写隧道/认证/库存。完整来源在方案末尾。
- 未读取真实配置、密码、私钥、会话、数据库或原始聊天；未安装任何软件，未改生产/DNS/网络，未推送Git或新增源manifest。

## 剩余工作与阻塞

本轮验证：Python3.15执行`tools/repo_check.py --output local/build/bore-own-ui-plan-20261026/repo-check.json`退出0，49项检查通过、0错误；保留既有production-py312-rebuild载荷未构建警告。`git diff --check`退出0；7份文档检查未发现断链或敏感字段模式。业务源码哈希未变；文档变更未运行组件业务测试（skipped），未将网络与生产验证算作通过。

1. 用户确认方案；需确认可用且可控制的免费公网资源/443、是否保留管理员内网维护，以及公网先只读的灰度策略。公共bore免费节点不保证标准443/稳定性/可信来源IP，不能据此承诺正式免费服务。
2. 恢复内网和DSH后先收回HTTPS最终备份/执行审计，查询实际项目数据库和网站模块反向依赖，不重新盲目部署或清理未知库。
3. 由原DSH session实施阶段任务，Codex复核；先隔离网络/来源IP与权限，再只读灰度、补业务UI、迁移客户端旧调用、最后收敛/可选卸载旧网站。
4. 性能、真实公网登录、写操作/并发/幂等、PROXY链路与卸载演练均未执行；现有HTTPS12检查和隔离登录13断言仅历史证据，不能当本轮安全通过。自动续期仍待实现。

## 依赖和产物

本轮仅Markdown方案/任务/交接及Git排除的路由清单，应用源不变。内网Odoo/核心stock/product/mrp依赖保留；lab_site/website物理卸载要另审依赖并获具体授权。没有额外付费服务或身份平台采购。

## 生产状态和回滚

本轮没有生产操作，无生产回滚动作。实际当前状态以2026-10-25-team-https-current.md及恢复连接后的核验为准。后续公网停用应只关闭项目隧道/监听，保留内网；UI回退不覆盖已产生的真实库存数据。
