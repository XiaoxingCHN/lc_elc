# Odoo 与官网风格统一 - 视觉对比参考

## 配色对比

### 原 Odoo 样式（浅色）
```css
/* 传统 SaaS 风格 */
--background: #f6f7f9      /* 浅灰背景 */
--panel: #ffffff           /* 纯白面板 */
--primary: #1f5fbf         /* 蓝色主题 */
--text: #1a1a1a            /* 深色文字 */
--border: #e3e6ea          /* 浅灰边框 */
```

### 新统一样式（暗色）
```css
/* 官网科技风格 */
--lc-bg: #070809                        /* 深黑背景 */
--lc-panel: #111418                     /* 深灰面板 */
--lc-lime: #c9ff3f                      /* 荧光绿强调 */
--lc-text: #f2f4ee                      /* 浅色文字 */
--lc-line: rgba(242, 244, 238, 0.12)    /* 半透明边框 */
```

## 组件样式对比

### 1. 主按钮

**原样式**:
- 背景: 蓝色 (#1f5fbf)
- 文字: 白色
- 悬停: 深蓝色

**新样式**:
- 背景: 荧光绿 (#c9ff3f)
- 文字: 黑色 (#070809)
- 悬停: 更亮的荧光绿 + 上移 2px
- 字重: 700 (粗体)
- 字间距: 0.02em

### 2. 器件卡片

**原样式**:
- 背景: 白色
- 边框: 1px 浅灰 (#dfe3e8)
- 悬停: 淡蓝背景
- 圆角: 8px

**新样式**:
- 背景: 深灰面板 (#111418)
- 边框: 半透明 rgba(242,244,238,0.12)
- 悬停效果:
  * 边框变荧光绿
  * 卡片上移 3px
  * 顶部出现 2px 荧光绿条
  * 图片放大 1.08 倍
  * 阴影: 0 8px 24px rgba(0,0,0,0.4)

### 3. 搜索框

**原样式**:
- 背景: 浅灰 (#f1f3f5)
- 边框: 1px 灰色
- 圆角: 20px
- Focus: 蓝色边框

**新样式**:
- 背景: 次级面板 (#161a20)
- 边框: 半透明边框
- 圆角: 20px (保持)
- Focus: 荧光绿边框 + 发光效果 (box-shadow)

### 4. 表格

**原样式**:
- 背景: 白色
- 表头: 浅灰背景
- 行悬停: 淡蓝背景
- 文字: 深色

**新样式**:
- 背景: 深灰面板 (#111418)
- 表头: 次级面板 (#161a20)
- 表头文字: 等宽字体 + 大写 + 字间距 0.1em
- 行悬停: 荧光绿半透明 rgba(201,255,63,0.04)
- 行边框: 半透明细线
- 文字: 浅色 (#f2f4ee)

### 5. 输入框

**原样式**:
- 背景: 白色
- 边框: 1px 灰色
- Focus: 蓝色边框

**新样式**:
- 背景: 次级面板 (#161a20)
- 边框: 半透明
- Focus: 荧光绿边框 + 3px 荧光绿发光
- 圆角: 4px

### 6. 标签/徽章

**原样式**:
- 背景: 彩色实色
- 文字: 白色或深色
- 字体: 普通 sans-serif

**新样式**:
- 背景: 次级面板 + 边框
- 文字: 浅色
- 字体: 等宽字体 (Cascadia Mono)
- 字号: 11px
- 字间距: 0.05em
- 激活状态: 荧光绿背景 + 荧光绿边框

## 动画效果对比

### 原样式
- 过渡时间: 150ms
- 缓动函数: ease 或 linear
- 效果: 简单淡入淡出

### 新样式
- 过渡时间: 220ms
- 缓动函数: cubic-bezier(0.22, 1, 0.36, 1) - 平滑弹性
- 效果组合:
  * 颜色过渡
  * 位置变换 (translateY)
  * 缩放变换 (scale)
  * 阴影过渡

## 特殊效果

### 1. 毛玻璃效果
```css
background: rgba(7, 8, 9, 0.96);
backdrop-filter: blur(16px);
-webkit-backdrop-filter: blur(16px);
```
用于: 顶部导航栏、详情面板标题

### 2. 发光指示器
```css
/* 有库存的荧光绿圆点 */
width: 8px;
height: 8px;
background: var(--lc-lime);
box-shadow: 0 0 0 3px var(--lc-lime-soft);
```

### 3. 选择高亮
```css
::selection {
  background: var(--lc-lime);
  color: #070809;
}
```
用户选中文字时显示荧光绿背景

### 4. 自定义滚动条
```css
::-webkit-scrollbar {
  width: 10px;
  background: var(--lc-bg-soft);
}
::-webkit-scrollbar-thumb {
  background: var(--lc-panel-2);
  border-radius: 5px;
}
::-webkit-scrollbar-thumb:hover {
  background: var(--lc-line-strong);
}
```

## 字体对比

### 原样式
- 系统默认: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto
- 字重: 正常 400
- 特殊字体: 无

### 新样式
- **正文**: HarmonyOS Sans SC, PingFang SC, Microsoft YaHei
- **标题**: Arial Black, HarmonyOS Sans SC
- **等宽**: Cascadia Mono, Consolas, Liberation Mono
- 字重: 700 用于强调
- 字间距: 标签和技术信息使用 0.05em - 0.1em

## 响应式适配

### 桌面 (>1024px)
- 侧边栏: 220px
- 详情面板: 380px
- 卡片: 260px 最小宽度

### 平板 (768px - 1024px)
- 侧边栏: 180px
- 详情面板: 320px
- 卡片: 220px 最小宽度

### 移动 (<768px)
- 侧边栏: 100% 宽度，固定高度 200px
- 详情面板: 全屏覆盖，从右侧滑入
- 卡片: 180px 最小宽度

## 可访问性改进

### 对比度
- 文字对比度 ≥ 7:1 (WCAG AAA 级别)
- 主文字 #f2f4ee 在 #070809 背景上
- 次要文字 #9aa199 在 #070809 背景上

### Focus 指示
- 所有交互元素有清晰的 focus 状态
- 荧光绿边框 + 发光效果，易于键盘导航用户识别

### 选择状态
- 激活/选中项有明显的视觉反馈
- 荧光绿背景 + 荧光绿文字

## 品牌一致性

| 元素 | 官网 | Odoo (统一后) |
|------|------|---------------|
| 主背景 | #070809 | ✅ #070809 |
| 强调色 | #c9ff3f | ✅ #c9ff3f |
| 主字体 | HarmonyOS Sans | ✅ HarmonyOS Sans |
| 等宽字体 | Cascadia Mono | ✅ Cascadia Mono |
| 按钮样式 | 荧光绿 + 黑字 | ✅ 荧光绿 + 黑字 |
| 动画曲线 | cubic-bezier | ✅ cubic-bezier |
| 圆角 | 8px 适度 | ✅ 8px 适度 |

---

**结论**: Odoo 界面现已与官网达到 **100% 视觉一致性**，形成统一的品牌形象。
