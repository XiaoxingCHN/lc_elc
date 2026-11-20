# 方案：管理员维护入口（自有 UI 替代 Odoo 原生后台）

- Status: **待审核**（未改任何源码）
- 用户诉求：
  > 必须把管理员维护入口做出来…不想继续使用 odoo 原生后台 UI 来管理整个账户和库存相关的，
  > 一是不统一，二是门户太乱不好管理，只需要提供一个特定入口或者是只有管理员账号登录时
  > 才有完全管理的界面

## 一、为什么以前没做（先认账）

`docs/architecture/TEAM_WAREHOUSE_FRAMEWORK_DRAFT.md:54` 有一条明写的范围边界：

> 原生后台供管理员低频维护，接受保留 `/odoo` 路径；成员日常流程使用自有页面。
> **若用户要求连管理员维护也完全重做，属于额外明确范围，不能默认纳入首轮。**

这条把「管理员维护」划到了首轮范围外，之后没人回头复查。我此前也按文档判断
「公网 `/web` 404 = 后台已关」，没意识到管理员仍要走内网 8069 的原生后台。

## 二、现状：管理员现在必须用原生后台做的事

| 任务 | 现有自有 UI | 现在怎么办 |
|---|---|---|
| 建用户 | ❌ | 内网 8069 → `/web` → 设置 → 用户 |
| 改密码 / 重置密码 | ❌ | 同上 |
| 停用账号 | ❌ | 同上 |
| 系统管理员 / ERP 权限组 | ❌ | 同上 |
| 编辑器件（名称/型号/封装/参数） | ❌ 只能绑 C 码、建档 | 同上 |
| 分类树维护 | ❌ | 同上 |
| 库存盘点 / 报废 / 调拨 | ❌ 后端刻意不提供 | 同上 |
| 模块安装 / 数据库 / 备份 | ❌ | CLI 脚本 |

**已有的**（`/team/lab/settings`）：只能开关「只读 / 操作员 / 管理员」三个库存角色。

## 三、方案：扩展现有「管理」页（不新建页面）

**按用户确认：维护界面放在原有的「管理」里，只给管理员显示。**

### 3.1 入口与门禁：**已经是管理员专属，无需任何改动**

核实结果（`controllers/common.py:304` + `WORKFLOW_NAV`）：

```python
'can_manage_members': manager      # manager = is_lab_manager(user)
('settings', 'can_manage_members', False),   # 导航项
```

也就是说：
- **「管理」页现在就只有 `group_lab_manager` 能看见**，普通操作员导航里没有这一项；
- 页面本身也走 `render_denied`，直接访问 URL 会被拒。

**所以「只给管理员显示」这条已经成立，本次不改权限、不加路由、不加导航。**
要做的只是往这个页面里填功能。

### 3.2 现有页面结构（`views/workflow_inventory.xml:332`）

```
workflow_inventory_settings
├─ 未决提交恢复区（data-lc-inv-locks="settings"）
├─ 成员库存角色说明面板
├─ 搜索工具条（query / only_with_role / 刷新）
├─ 账号与角色表格（姓名 登录名 用户 操作员 管理员 状态）
└─ 「不在本页的配置」面板   ← 这一段就是要被替换掉的
```

最后那个「不在本页的配置」面板现在写着：

> 系统管理员、ERP 管理员的授权仍走原生后台…
> 数据库、模块安装、密码复位不在本页；密码请走管理员复位或原生流程。

**这三条就是本次要消灭的缺口。**

### 3.3 在「管理」页内新增三块

#### 页签 1：账号管理

| 功能 | 需要的新端点 | 说明 |
|---|---|---|
| 列出账号 | 复用 `members` | **已有** |
| 角色开关 | 复用 `member_set_role` | **已有** |
| 建用户 | `POST /lab/api/admin/user_create` | 新增：login/name/password/初始角色 |
| 改密码 | `POST /lab/api/admin/user_set_password` | 新增：管理员代设 |
| 停用/启用 | `POST /lab/api/admin/user_toggle_active` | 新增：不能停用自己、不能停用最后一个管理员 |
| 系统权限组 | `POST /lab/api/admin/user_set_system_group` | 新增：仅 `base.group_system` 持有者可用 |

#### 页签 2：器件档案

| 功能 | 需要的新端点 |
|---|---|
| 编辑产品字段 | `POST /lab/api/admin/product_update`（名称/型号/封装/品牌/参数） |
| 分类树 | `POST /lab/api/admin/category_create` / `category_update` / `category_delete` |

#### 页签 3：库存调整（**最后做，风险最高**）

| 功能 | 实现方式 |
|---|---|
| 盘点 | 建 `stock.move` → `_action_done()`，**绝不直接写 `stock.quant`** |
| 报废 | 走 `stock.scrap` |
| 库位调拨 | 建两笔 `stock.move`（出+入） |

**约束**：全部复用 `lab_workflow_common._lab_move`（`lab_workflow_common.py:1053`），
它是现有所有库存变动的唯一通道，保证批次/并发/UoM 语义一致。

### 3.5 需要改动的文件（**不新建页面**）

```
server/ubuntu22.04/odoo_addons/lab_workflow/controllers/lab_admin_api.py   # 新：管理端点
server/ubuntu22.04/odoo_addons/lab_workflow/models/lab_admin.py            # 新：业务逻辑
server/ubuntu22.04/odoo_addons/lab_workflow/controllers/__init__.py        # 注册
server/ubuntu22.04/odoo_addons/lab_workflow/models/__init__.py             # 注册
server/ubuntu22.04/odoo_addons/lab_team_web/controllers/common.py          # 加端点映射
server/ubuntu22.04/odoo_addons/lab_team_web/views/workflow_inventory.xml   # 改：扩 settings 模板
server/ubuntu22.04/odoo_addons/lab_team_web/static/src/js/pages/settings.js # 改：加三块交互
```

**不新增** `workflow_admin.xml`、`admin.js`、路由、导航项——全部并入现有「管理」页。

## 四、安全约束（必须先写进实现）

1. **不能用 sudo 绕过业务规则**。现有 `_lab_member_set_role_once` 用了
   `env['res.users'].sudo()`，但那是「管理员已过门禁、只是绕过记录规则」的场景。
   新建用户同理，但**必须在服务端校验**：不能建 `base.group_system` 用户除非操作者自己
   就是系统管理员。
2. **不能停用最后一个管理员**（沿用现有 `_lab_manager_remaining_by_company` 的 fail-closed 逻辑）。
3. **不能停用自己**。
4. **库存调整必须留审计**：`lab.operation` 里记一条，含操作人、目标库位、数量、原因。
5. **密码不落日志**（沿用 `redactForLog`）。

## 五、分批与工期估算

| 批次 | 内容 | 风险 | 估算 |
|---|---|---|---|
| A | `/team/admin` 骨架 + 页签 1（账号管理） | 低 | 主要工作量 |
| B | 页签 2（器件档案） | 中（改 product.template） | 中等 |
| C | 页签 3（库存调整） | **高**（直接动库存） | 需要最谨慎 |

建议：**A 先做并验收，B、C 分开做**。

## 六、待你确认

1. ~~入口形式~~ → **已确认：扩展现有「管理」页，只给管理员显示**
2. ~~谁算管理员~~ → **已确认：「管理」页现在就是 `group_lab_manager` 专属，
   沿用即可**。唯一要额外考虑的是「系统权限组」这块——授予 `base.group_system`
   是 Odoo 系统级操作，建议这一项额外要求操作者自己就是系统管理员。
3. **库存调整要不要做**？这是唯一会直接改库存的入口，风险最高。
   可以只做「盘点」，不做「报废/调拨」。
4. **`mrp` / `website` 清理**：你说「也可以不管」，那我先跳过，只做管理员入口？

## 七、页面布局（扩展现有「管理」页后的样子）

```
/team/lab/settings  「管理」
├─ [现有] 未决提交恢复区
├─ [现有] 成员库存角色说明
├─ [现有] 搜索工具条
├─ [现有] 账号与角色表格
│
├─ [新增] 账号管理
│    ├─ 新建账号（登录名 / 姓名 / 初始密码 / 初始角色）
│    ├─ 重置密码（选账号 → 输入新密码）
│    └─ 停用 / 启用
│
├─ [新增] 器件档案维护
│    ├─ 搜索器件 → 编辑名称/型号/封装/品牌/参数
│    └─ 分类树（新增 / 改名 / 删除）
│
└─ [新增] 库存调整（若确认要做）
     └─ 选库位 → 选器件 → 盘点数量 / 报废
        （全部走 stock.move，不直写 stock.quant）
```

原来那段「不在本页的配置」删除或改写——它列的三条缺口正是本次要消灭的。
