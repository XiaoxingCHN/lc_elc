# Odoo 全局暗色主题 - 最终部署方案

**日期**: 2026-10-24  
**问题**: 之前的主题只在 lab_catalog 生效，未覆盖整个 Odoo  
**解决**: 创建独立的 lab_theme 模块，全局应用暗色主题

---

## 🎯 问题回顾

### 发现的问题
1. ❌ 左侧边栏仍是浅色背景
2. ❌ 主内容区域仍是浅灰色
3. ❌ lab_portal 模块导致 JavaScript 错误
4. ❌ 暗色主题未全局生效

### 根本原因
- 之前的 `lc_theme_dark.css` 只在 `lab_catalog` 模块中加载
- 仅影响 lab_catalog 相关页面
- 其他 Odoo 界面（设置、用户管理等）仍为默认浅色

---

## ✅ 解决方案

### 创建独立全局主题模块

**模块名称**: `lab_theme`  
**位置**: `server/ubuntu22.04/odoo_addons/lab_theme`  
**功能**: 全局暗色主题，覆盖整个 Odoo 后台

**关键配置**:
```python
"assets": {
    "web.assets_backend": [
        ("prepend", "lab_theme/static/src/css/global_dark_theme.css"),
    ],
}
```

使用 `"prepend"` 确保 CSS 最优先加载，覆盖所有默认样式。

---

## 📦 模块文件

```
server/ubuntu22.04/odoo_addons/
├── lab_theme/                          ← 新建全局主题模块
│   ├── __init__.py
│   ├── __manifest__.py
│   ├── README.md
│   ├── deploy-theme.sh
│   ├── static/src/css/
│   │   └── global_dark_theme.css       (13.3 KB - 增强版暗色主题)
│   └── security/
│       └── ir.model.access.csv
│
└── lab_catalog/                        ← 保持不变
    └── static/src/css/
        └── lc_theme_dark.css           (保留作为备份)
```

**已删除**: `lab_portal` 模块（导致错误，不需要）

---

## 🚀 部署步骤

### 方式一：使用部署脚本（推荐）

```bash
# 1. 上传 lab_theme 整个目录到服务器
scp -r F:\lc_elc\server\ubuntu22.04\odoo_addons\lab_theme \
    hbut@192.168.31.105:/opt/odoo/addons/

# 2. 如果服务器上有 lab_portal，先删除它
ssh hbut@192.168.31.105
cd /opt/odoo/addons
rm -rf lab_portal

# 3. 运行部署脚本
cd /opt/odoo/addons
bash lab_theme/deploy-theme.sh lc_hardware

# 4. 清除浏览器缓存
# Ctrl + Shift + R
```

### 方式二：手动部署

```bash
# 1. SSH 连接服务器
ssh hbut@192.168.31.105

# 2. 删除 lab_portal（如果存在）
cd /opt/odoo/addons
rm -rf lab_portal

# 3. 确认 lab_theme 已上传
ls -la lab_theme/

# 4. 安装 lab_theme 模块
sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo-bin \
    -c /etc/odoo/odoo.conf \
    -d lc_hardware \
    -i lab_theme \
    --stop-after-init

# 5. 重启 Odoo
sudo systemctl restart odoo

# 6. 检查服务状态
sudo systemctl status odoo

# 7. 浏览器强制刷新
# Ctrl + Shift + R
```

---

## ✅ 验收清单

### 整体界面
- [ ] 访问任何 Odoo 页面，背景为深黑色 (#070809)
- [ ] 顶部导航栏为半透明黑色 + 毛玻璃效果
- [ ] 左侧边栏（应用菜单）为深色背景
- [ ] 主内容区域为深色背景

### 具体页面测试
- [ ] **设置页面** - 深色背景
- [ ] **用户管理** - 深色背景，表格单元格深色
- [ ] **元器件档案** - 深色背景，表格单元格深色
- [ ] **任何列表视图** - 表头深灰，单元格深色，文字白色
- [ ] **任何表单视图** - 深色面板，输入框深色背景

### 关键检查点
- [ ] 所有文字清晰可读（白色 #f2f4ee）
- [ ] 没有白色或浅灰色的大块区域
- [ ] 顶部菜单无紫色残留
- [ ] 按钮为荧光绿色 (#c9ff3f)
- [ ] 表格行悬停有荧光绿半透明效果
- [ ] 无 JavaScript 错误

---

## 🔍 故障排查

### 问题：样式仍然是浅色

**检查步骤**:
1. 确认 `lab_theme` 模块已安装
   ```bash
   # 在 Odoo 界面
   应用 → 搜索 "lab_theme" → 状态应为"已安装"
   ```

2. 检查 CSS 是否加载
   ```
   浏览器 F12 → Network → 搜索 "global_dark_theme.css"
   应该看到状态 200
   ```

3. 清除所有缓存
   ```bash
   # Odoo 资产缓存
   设置 → 开发者工具 → 清除资产缓存
   
   # 浏览器缓存
   Ctrl + Shift + Delete → 清除全部
   ```

4. 检查模块依赖
   ```bash
   # 确认 web 模块已安装
   grep "depends" /opt/odoo/addons/lab_theme/__manifest__.py
   应该看到: "depends": ["web"]
   ```

### 问题：JavaScript 错误

**解决方案**:
```bash
# 确认 lab_portal 已删除
ls /opt/odoo/addons/ | grep portal
# 不应该有输出

# 如果仍存在，删除它
rm -rf /opt/odoo/addons/lab_portal

# 重启 Odoo
sudo systemctl restart odoo
```

### 问题：部分页面是浅色，部分是深色

**原因**: 浏览器缓存  
**解决**: 强制刷新每个标签页（Ctrl+Shift+R）

---

## 📊 对比效果

### 部署前
- 左侧边栏：白色/浅灰 ❌
- 主内容区：浅灰色 ❌
- 表格：白色背景 ❌
- 文字：深灰色（在白底上）❌

### 部署后
- 左侧边栏：深黑色 (#070809)✅
- 主内容区：深黑色 (#070809)✅
- 表格：深灰背景 (#111418)✅
- 文字：白色 (#f2f4ee)✅
- 强调色：荧光绿 (#c9ff3f)✅

---

## 🎨 风格一致性

部署后，整个 Odoo 后台将与官网 **l-creation.club** 完全一致：

| 元素 | 官网 | Odoo（部署后）|
|------|------|---------------|
| 背景 | #070809 | ✅ #070809 |
| 面板 | #111418 | ✅ #111418 |
| 文字 | #f2f4ee | ✅ #f2f4ee |
| 强调色 | #c9ff3f | ✅ #c9ff3f |
| 字体 | HarmonyOS Sans | ✅ HarmonyOS Sans |
| 动画 | cubic-bezier | ✅ cubic-bezier |

---

## 📝 后续维护

### 更新主题样式

```bash
# 1. 修改 CSS
vi /opt/odoo/addons/lab_theme/static/src/css/global_dark_theme.css

# 2. 清除缓存 + 重启
# Odoo 界面 → 清除资产缓存
sudo systemctl restart odoo
```

### 回滚到默认主题

```bash
# 卸载 lab_theme
sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo-bin \
    -c /etc/odoo/odoo.conf \
    -d lc_hardware \
    --uninstall lab_theme \
    --stop-after-init

sudo systemctl restart odoo
```

---

## 🎯 预期最终效果

部署完成后：

1. **访问任何 Odoo 页面** → 整体深黑色背景
2. **打开设置菜单** → 所有选项深色背景
3. **查看任何列表** → 表格深色，文字白色，清晰可读
4. **编辑任何表单** → 深色面板，输入框深色
5. **悬停按钮/链接** → 荧光绿高亮效果
6. **无任何 JavaScript 错误**

整个系统从视觉上与官网完全统一，形成完整的品牌体验！

---

**实施人员**: Kiro AI  
**部署状态**: 准备完成，待服务器部署  
**文档版本**: 1.0 - 最终方案
