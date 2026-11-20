# 方案：把所有管理员维护操作收进「管理」页

- Status: **待审核**（未改任何源码）
- 用户需求（本轮澄清后）：
  > 我们现在要把所有的管理员相关的东西（注意边界主要是维护的相关内容我们没有在自己的
  > UI 里做）全部拉出来放在管理里

即：**「管理」页 = 维护操作的唯一入口**，不再需要去 Odoo 原生后台。

## 一、为什么以前没做（先认账）

`docs/architecture/TEAM_WAREHOUSE_FRAMEWORK_DRAFT.md:54` 有一条明写的范围边界：

> 原生后台供管理员低频维护，接受保留 `/odoo` 路径；成员日常流程使用自有页面。
> **若用户要求连管理员维护也完全重做，属于额外明确范围，不能默认纳入首轮。**

这条把「管理员维护」划到了首轮范围外，之后没人回头复查。

## 二、前提已成立：管理页本来就是管理员专属

```python
# controllers/common.py:304
'can_manage_members': manager          # manager = is_lab_manager(user)
# WORKFLOW_NAV
('settings', 'can_manage_members', False),
```

非管理员导航里没有这一项，直接访问 URL 也会 `render_denied`。
**本次不改权限、不加路由、不加导航，只往这个页面里填功能。**

## 三、边界：原生后台里到底有什么

生产实际顶层菜单：

```
实验室库存   ← 我们自己的，已全部指向 /team/*
Website      ← 门户，本次不关心
Settings     ← ★ 维护面主体
Apps         ← 模块安装
Discuss      ← 聊天，不用
Inventory    ← ★ 库存维护主体
Link Tracker ← 营销，不用
Manufacturing← 制造，不用（mrp 0 数据）
```

### 3.1 需要搬的：`Settings` 里与我们相关的

| 原生路径 | 内容 | 是否搬 |
|---|---|---|
| Users & Companies → **Users** | 建用户、改密码、停用 | ✅ 搬 |
| Users & Companies → **Groups** | 组与权限 | ⚠️ 部分（库存三组 + 系统管理员开关） |
| Users & Companies → **Companies** | 公司信息 | ✅ 搬（只读 + 改名） |
| **General Settings** | 站点标题等 | ✅ 搬 |
| Technical → **System Parameters** | `lab_team_web.*` 等配置 | ✅ 搬（键白名单） |
| Technical → **Sequences** | 编码序列 | ✅ 搬（只读 + 重置） |
| Technical → 其它（Views/Actions/Menus/…） | 开发调试 | ❌ 不搬（内网保留） |

### 3.2 需要搬的：`Inventory` 里与我们相关的

| 原生路径 | 内容 | 是否搬 |
|---|---|---|
| Products → **Products** | 编辑器件 | ✅ 搬 |
| Products → **Product Categories** | 分类树 | ✅ 搬 |
| Operations → **Physical Inventory** | 盘点 | ✅ 搬（走 stock.move） |
| Operations → **Scrap** | 报废 | ⚠️ 待确认 |
| Reporting → **Stock** | 库存报表 | ✅ 搬（只读） |
| Configuration → Warehouses/Locations | 仓库/库位 | ✅ 已有（`/team/lab/locations`） |

### 3.3 明确不搬的

- `Apps`（模块安装）→ 继续用 `upgrade_modules.sh`
- `Website` / `Link Tracker` / `Manufacturing` / `Discuss` → 不用
- `Settings → Technical` 里的 Views/Actions/Menus/User Interface → 开发调试，内网保留
- 备份/恢复 → 继续用 `odoo_backup.py` / `odoo_restore.py`

## 四、改造后的「管理」页结构

```
/team/lab/settings  「管理」（group_lab_manager 专属）
│
├─ [现有] 未决提交恢复区
├─ [现有] 成员库存角色（勾选框）
│
├─ [新] 账号
│    ├─ 新建账号：登录名 / 姓名 / 初始密码 / 初始库存角色
│    ├─ 重置密码：选账号 → 新密码
│    ├─ 停用 / 启用
│    └─ 系统管理员开关（仅 base.group_system 持有者可改）
│
├─ [新] 器件与分类
│    ├─ 搜索器件 → 编辑 名称/型号/封装/品牌/参数
│    └─ 分类树：新增 / 改名 / 删除（有库存的分类禁止删）
│
├─ [新] 库存
│    ├─ 盘点：选库位 + 器件 → 实际数量 → 生成 stock.move
│    ├─ 报废：（待确认）
│    └─ 库存报表：按库位/器件查看 quant（只读）
│
├─ [新] 系统参数
│    ├─ 站点标题、管理 Host 等白名单键
│    └─ 编码序列（只读 + 重置）
│
└─ [删除] 「不在本页的配置」说明块
     （它列的三条缺口正是本次要填的）
```

## 五、需要新增的端点

全部 `POST /lab/api/admin/*`，`auth='user'`，**`_lab_require_manager` 门禁**：

| 端点 | 用途 | 备注 |
|---|---|---|
| `user_create` | 建账号 | 校验登录名唯一、密码强度 |
| `user_set_password` | 重置密码 | 不落日志 |
| `user_toggle_active` | 停用/启用 | 不能停用自己、不能停用最后一个管理员 |
| `user_set_system_group` | 系统管理员开关 | **额外要求操作者是 `base.group_system`** |
| `product_update` | 编辑器件 | 白名单字段 |
| `category_create/update/delete` | 分类树 | 有库存的分类禁止删 |
| `stock_adjust` | 盘点 | **必须走 `stock.move` + `_action_done()`** |
| `stock_report` | 库存报表 | 只读 quant |
| `config_get/set` | 系统参数 | 键白名单 |
| `sequence_list/reset` | 编码序列 | 只读 + 重置 |

## 六、安全约束（实现时必须遵守）

1. **库存调整只能走 `stock.move`**，复用 `lab_workflow_common._lab_move`
   （`lab_workflow_common.py:1053`），绝不直接写 `stock.quant`。
2. **不能停用最后一个管理员**（沿用 `_lab_manager_remaining_by_company` 的 fail-closed）。
3. **不能停用自己**。
4. **授予 `base.group_system` 要求操作者自己就是系统管理员**（不能靠库存管理员提权）。
5. **密码不落日志**（沿用 `redactForLog`）。
6. **所有写操作记审计**：`lab.operation` 或 `_logger.info`，含操作人/目标/变更内容。
7. **系统参数白名单**：只允许改 `lab_team_web.*`、`lab_workflow.*` 前缀的键，
   不允许改 `database.*`、`auth.*` 等。

## 七、分批建议

| 批次 | 内容 | 风险 | 说明 |
|---|---|---|---|
| **A** | 账号（建/改密/停用/系统组） | 低 | 最急迫，现在完全缺失 |
| **B** | 器件与分类 | 中 | 改 product.template，需白名单字段 |
| **C** | 系统参数 + 序列 | 低 | 白名单键 |
| **D** | 库存报表（只读） | 低 | 先只读，建立信心 |
| **E** | 库存调整（盘点/报废） | **高** | 唯一直接改库存的，最后做 |

## 八、待确认

1. **报废**要不要做？（盘点我建议做，报废风险更高）
2. **系统参数**允许改哪些键？我建议只开 `lab_team_web.*` 和 `lab_workflow.*`。
3. **分类树删除**：有库存的分类禁止删，没库存的允许删——这样行吗？
4. **批次顺序**：A（账号）先做？
