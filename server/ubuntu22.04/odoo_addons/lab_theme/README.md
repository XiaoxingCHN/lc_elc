# Lab Theme - 力创暗色主题模块

全局暗色科技风主题，与官网 l-creation.club 风格完全统一。

## 功能

- 覆盖整个 Odoo 后台界面
- 深黑背景 (#070809) + 荧光绿强调色 (#c9ff3f)
- 高对比度文字，WCAG AAA 级别
- 优先级最高，确保全局生效

## 安装

```bash
# 安装模块
odoo-bin -c /etc/odoo/odoo.conf -d lc_hardware -i lab_theme --stop-after-init
sudo systemctl restart odoo

# 或使用部署脚本
bash deploy-theme.sh
```

## 卸载

如需恢复 Odoo 默认主题：

```bash
odoo-bin -c /etc/odoo/odoo.conf -d lc_hardware --uninstall lab_theme --stop-after-init
sudo systemctl restart odoo
```

## 注意事项

- 本模块使用 "prepend" 确保 CSS 优先加载
- 安装后需清除浏览器缓存（Ctrl+Shift+R）
- 打印时自动切换为浅色样式

## 版本

- 当前版本: 19.0.1.0.0
- Odoo 版本: 19.0
- 依赖: web

## 作者

lc_elc - 力创实验室
