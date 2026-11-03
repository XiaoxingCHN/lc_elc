# lab_theme 全局暗色主题 - 部署验收记录

**执行时间**: 2026-10-25 00:32–00:47 (UTC 16:32–16:47)
**执行人**: AI 助手（本轮用户授权直接部署）
**目标环境**: http://192.168.31.105:8069 （对外 lc.rm.com）
**数据库**: LcHardwareHouse（生产业务库）

## 一、部署结果

| 项目 | 状态 |
|---|---|
| lab_theme 模块 | installed 19.0.1.0.1 |
| lab_portal（错误方案残留） | uninstalled，已清理 |
| lab_catalog | installed 19.0.2.0.4（未动） |
| lab_inventory | installed 19.0.1.0.0（未动） |
| lab_workflow | installed 19.0.1.2.0（未动） |
| Odoo 服务 | active |

### 资产包验证（关键证据）

| 资产包 | 大小 | `--lc-bg` 出现次数 |
|---|---|---|
| web.assets_backend | 1,222,320 B | 23 |
| web.assets_frontend_minimal | 14,308 B | 11 |
| web.assets_frontend (min) | 810,445 B | 11 |

CSS 源码直连：`GET /lab_theme/static/src/css/global_dark_theme.css` → 200, 14,172 B

### 业务数据不变

| 指标 | 部署前 | 部署后 |
|---|---|---|
| stock_quant | 2 | 2 |
| stock_move | 1 | 1 |
| product_product | 2 | 2 |

## 二、过程中修复的两个真实问题

1. **模块装错数据库**
   第一次误装到空库 `lc_hardware`；业务库是 `LcHardwareHouse`。已在正确库安装。

2. **登录页仍为浅色**
   登录页用的是 `web.assets_frontend` / `web.assets_frontend_minimal`，不是 backend 包。
   已在 manifest 中同时 prepend 到三个包，重新升级后生效。

3. **lab_portal 残留报错**
   早上实验用门户模块源码已删，但库里仍记录 installed，导致每次启动
   `Some modules are not loaded: ['lab_portal']`。已通过 Odoo ORM
   `button_immediate_uninstall()` 正规卸载。

## 三、未验证项（不得算通过）

- [ ] **浏览器视觉验收未做**：本轮只能验证资产包内含主题规则，未在真实浏览器截图确认最终渲染效果（配色、对比度、表格可读性）。
- [ ] 移动端/平板渲染未验证。
- [ ] 标签打印样式未实测（CSS 内含 @media print 回退浅色，但未打印验证）。
- [ ] 前台 Website 页面（若有对外页面）整体变暗是否符合预期，未确认。
- [ ] 部分组件（日期选择器、富文本编辑器、看板拖拽）未逐一目视检查。

## 四、回滚方式

```bash
sudo systemctl stop odoo
sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo-19/odoo-bin \
    -c /etc/odoo.conf -d LcHardwareHouse --uninstall lab_theme --stop-after-init
sudo systemctl restart odoo
```
该模块只提供 CSS 资产，不建表、不改业务数据，卸载即可完全回退。

## 五、环境事实（本次核实）

| 项 | 值 |
|---|---|
| Odoo 版本 | 19.0 |
| odoo-bin | /opt/odoo/odoo-19/odoo-bin |
| 配置 | /etc/odoo.conf（不是 /etc/odoo/odoo.conf） |
| Python venv | /opt/odoo/venv/bin/python3 |
| 自定义 addons | /opt/odoo/custom-addons |
| 服务 | systemd `odoo.service`，ExecStart 用 --config=/etc/odoo.conf |
| 数据库 | lc_hardware（空壳）, LcHardwareHouse（生产） |

## 六、SSH 插件问题定位（本轮一并解决）

DSH 的 SSH 插件（`@linxin666/dsh-ssh` 0.4.8）主机清单存放于：

```
$DSH_HOME/dsh-ssh.json   →  C:\Users\XIAOXINGCHN\.dsh\dsh-ssh.json
格式: { "version": 1, "hosts": [ {alias, host, port, user, auth:{kind,password}, proxyJump, tags, createdAt, updatedAt} ] }
```

此前该文件从未创建（也没在 GUI 里加过主机），所以 `ssh_list` 恒为空、
`ssh_exec` 报 "alias not found"。补上该文件后工具即恢复正常。
**注意**：密码以明文存在该文件中，属于本机用户自有文件，不可外传或提交 Git。
