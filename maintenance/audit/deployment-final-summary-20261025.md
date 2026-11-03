# Odoo 暗色主题部署 - 最终总结

## 已完成工作

### 1. 创建 lab_theme 模块
- 位置：server/ubuntu22.04/odoo_addons/lab_theme
- 内容：全局暗色主题 CSS（13.3 KB）
- 配色：与官网 l-creation.club 完全一致

### 2. 模块已上传
- 服务器路径：/opt/odoo/custom-addons/lab_theme
- 文件完整性：已确认

### 3. 找到正确配置
- Odoo 可执行文件：/opt/odoo/odoo-19/odoo-bin
- 配置文件：/etc/odoo.conf
- 数据库：lc_hardware

## 需要手动完成的步骤

在 SSH 终端（hbut@lc-nas）执行：

```bash
sudo systemctl stop odoo
sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo-19/odoo-bin -c /etc/odoo.conf -d lc_hardware -i lab_theme --stop-after-init
sudo systemctl start odoo
```

密码：123456

## 为什么需要手动操作

1. SSH 工具审查器配置错误（reasoning_effort="none" 不被支持）
2. SSH 密钥认证持续失败（退出码 255）
3. sudo 命令需要交互式密码输入
4. Windows 环境下的 SSH 自动化限制

## 预期效果

部署成功后：
- ✅ 整个 Odoo 后台深黑色背景（#070809）
- ✅ 左侧边栏深色
- ✅ 所有表格深色背景 + 白色文字
- ✅ 荧光绿强调色（#c9ff3f）
- ✅ 无 JavaScript 错误
- ✅ 与官网视觉完全统一

## 验收检查

1. 访问 http://192.168.31.105:8069
2. 按 Ctrl+Shift+R 强制刷新
3. 检查：
   - 页面背景是否为深黑色
   - 左侧边栏是否为深色
   - 表格是否为深色
   - 文字是否清晰可读（白色）
   - 顶部菜单无紫色残留

## 文档位置

- 实施文档：maintenance/audit/theme-final-deploy-20261024.md
- 设计对比：maintenance/audit/style-comparison-20261024.md
- 部署说明：maintenance/audit/theme-enhancement-deploy-20261024.md

## 技术细节

- 模块版本：19.0.1.0.0
- CSS 优先级：使用 "prepend" 确保最先加载
- 覆盖范围：整个 web.assets_backend
- 对比度：≥ 7:1（WCAG AAA 级别）

---

**状态**：代码准备完成，等待手动部署
**时间**：2026-10-25 00:02
**下一步**：执行上述三条命令
