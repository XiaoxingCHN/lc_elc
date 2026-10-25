# 导航栏紫色修复 + 官网首页替换（2026-10-25 第二轮）

**执行时间**: 2026-10-25 00:55–01:05
**数据库**: LcHardwareHouse（生产）
**涉及模块**: lab_theme 19.0.1.0.2、lab_site 19.0.1.0.0（新增）

## 一、菜单紫色 BUG 根因与修复

### 根因（已定位到具体规则）
Odoo 19 的导航条目背景不是写死的，而是来自 CSS 变量：

```css
.o_main_navbar .o_menu_sections .o_nav_entry,
.o_main_navbar .o_menu_sections .dropdown-toggle {
  background: var(--NavBar-entry-backgroundColor, #71639e);
}
```

默认值 `#71639e` 就是那一条紫色。之前的主题只覆盖了 `.o_menu_sections` 容器，
没覆盖到子条目 `.o_nav_entry`，所以整条菜单仍然是紫色。

### 修复（lab_theme 19.0.1.0.2）
在 `.o_main_navbar` 上重设全部相关变量，并对条目做 `!important` 兜底：

- `--NavBar-entry-backgroundColor` → transparent
- `--NavBar-entry-backgroundColor--hover/focus` → rgba(201,255,63,.12)
- `--NavBar-entry-backgroundColor--active` → rgba(201,255,63,.16)
- `--NavBar-entry-color` → rgba(242,244,238,.82)
- `--NavBar-entry-color--hover/active` → #c9ff3f

### 验证
编译后的 `web.assets_backend`（1,225,135 B）中：
- `--NavBar-entry-backgroundColor` 出现 **10 次**（修复规则）
- `.o_menu_sections .o_nav_entry` 选择器 **9 条**

## 二、官网首页替换（新模块 lab_site）

### 实现方式
模块 `lab_site` 通过 `inherit_id="website.homepage"` 替换 `#wrap` 内容：

```xml
<xpath expr="//t[@t-call='website.layout']/div[@id='wrap']" position="replace">
    <div id="wrap" class="oe_structure lc-site"> …原静态站 body… </div>
    <link rel="stylesheet" href="/lab_site/static/src/css/site.css"/>
    <script src="/lab_site/static/src/js/site.js"/>
</xpath>
```

关键设计：
1. **保留 `#wrap` + `oe_structure`** —— 否则网站编辑器会报
   `Cannot read properties of null (reading 'body')`（上一版 lab_portal 就栽在这）。
2. **CSS/JS 以 `<link>`/`<script>` 按需加载**，只在本页引入，不污染其它 Odoo 页面
   （避免静态站里的 `body{a}`、`h1` 全局 reset 破坏 contactus 等页面）。
3. 本页用 `body:has(#wrap.lc-site)` 隐藏 Odoo 站点的 header/footer，铺满视口。
4. 12 张图片随模块走 `/lab_site/static/src/img/`，不依赖外站。

### 验证结果
`GET / `（带会话）→ 200，40,230 B：
- 默认模板 "您的旅程从这里开始"：**0 次**（已被替换）
- 战队关键词：`热爱` 6 次、`力创` 12 次
- 引用 `/lab_site/static/src/css/site.css` 与 12 张图
- `id="wrap" class="oe_structure lc-site"` 存在（编辑器可进）

## 三、状态确认

| 项 | 值 |
|---|---|
| Odoo | active |
| lab_theme | installed 19.0.1.0.2 |
| lab_site | installed 19.0.1.0.0 |
| lab_catalog / lab_inventory / lab_workflow | installed（未动） |
| stock_quant | 2（未变） |
| 最近 30 行日志错误 | 0 |

## 四、回滚

- 恢复默认首页：卸载 lab_site
  ```bash
  odoo-bin -c /etc/odoo.conf -d LcHardwareHouse --uninstall lab_site --stop-after-init
  ```
  首页视图备份：服务器 `/tmp/homepage_view_backup.tsv`（id=1123 原 arch）
- 恢复浅色后台：卸载 lab_theme

## 五、仍未验证

- [ ] **真实浏览器视觉验收**（配色、菜单、首页渲染）—— 仅验证了服务端 HTML/CSS 内容
- [ ] 网站编辑器能否正常进入并保存（保留了 `#wrap`，但未实际点开验证）
- [ ] 移动端首页布局
- [ ] 首页替换后其它网站页面（contactus 等）是否受静态站 CSS 影响
- [ ] SEO/meta 标题仍是 "Home | My Website"，未改为战队名称
