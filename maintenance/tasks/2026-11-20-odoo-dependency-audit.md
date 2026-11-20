# Odoo 依赖详细梳理

- 日期：2026-11-20
- 对象：`lc-nas` 上的 `LcHardwareHouse` 库（Odoo 19）
- 结论先行：**我们对 Odoo 的依赖比预想的窄得多，但有一处不可替代。**

## 一、实际安装的 55 个模块

```
api_doc  auth_passkey  auth_passkey_portal  auth_signup  auth_totp  auth_totp_mail
auth_totp_portal  barcodes  barcodes_gs1_nomenclature  base  base_import
base_import_module  base_install_request  base_setup  bus  digest  google_gmail
google_recaptcha  html_builder  html_editor  http_routing  iap  iap_mail
lab_catalog  lab_inventory  lab_site  lab_team_web  lab_theme  lab_workflow
mail  mail_bot  microsoft_outlook  mrp  partner_autocomplete  phone_validation
portal  privacy_lookup  product  resource  resource_mail  rpc  sms  snailmail
social_media  stock  stock_sms  theme_default  uom  utm  web  web_tour
web_unsplash  website  website_mail  website_sms
```

其中**我们写的只有 6 个**：`lab_workflow`、`lab_catalog`、`lab_inventory`、
`lab_team_web`、`lab_theme`、`lab_site`。其余 49 个全是 Odoo 自带。

## 二、真正用到的 Odoo 模型（按引用次数）

| 模型 | 引用 | 用途 | 可替代性 |
|---|---|---|---|
| `product.template` | 51 | 器件档案主表 | **不可替代** |
| `res.users` | 29 | 账号、领用人 | **不可替代** |
| `stock.location` | 27 | 库位 | **不可替代** |
| `stock.quant` | 24 | **库存真值** | **不可替代** |
| `stock.move` / `stock.move.line` | 7 | **所有库存变动的唯一通道** | **不可替代** |
| `stock.lot` | 2 | 批次/袋 | 不可替代 |
| `stock.warehouse` | 5 | 仓库根 | 不可替代 |
| `product.category` | 4 | 分类 | 不可替代 |
| `ir.sequence` | 9 | 编码生成 | 可自建 |
| `ir.config_parameter` | 18 | 配置 | 可自建 |
| `ir.http` / `ir.ui.menu` / `ir.model.data` | 6 | 路由与菜单 | 可自建 |

## 三、核心结论：库存不能脱离 Odoo stock

`lab_workflow_common.py:1053-1094` 的 `_lab_move` 是**所有库存变动的唯一出口**：

```python
Move = self.env['stock.move']
MoveLine = self.env['stock.move.line']
move = Move.create({...})
MoveLine.create({...})
move.with_context(lab_workflow_move=True)._action_done()
if move.state != 'done':
    raise LabApiError.precondition('库存移动未完成…已回滚本次操作')
```

入库、领料、归还、历史库存分袋适配——**全部**经过它。

这意味着：只要保留 `stock` 模块，库存就是 Odoo 的 `stock.quant`/`stock.move`；
一旦想脱离 `stock`，等于自己重写一套库存引擎（含 `_action_done` 的
并发、批次、UoM、库位层级语义）。**不建议。**

## 四、可以关掉的

### 4.1 `mrp`（制造）——完全没用

| 证据 | 值 |
|---|---|
| `mrp_bom` 记录数 | **0** |
| `lab_allocation` 非 NONE 的 BOM 行 | **0** |
| 我们的代码引用 `mrp.*` | **仅一处**：`lab_inventory/models/mrp_bom_line.py` 给 `mrp.bom.line` 加两个字段，且**无任何代码读写** |

`lab_inventory/__manifest__.py` 声明 `depends: ['stock','product','mrp']`，
但那两个字段从来没被用过。

**依赖面核实**：全库 `depends mrp` 的模块只有 `lab_inventory` 一个，
没有其它模块依赖它。所以关掉 `mrp` 只需删掉 `mrp_bom_line.py` 和
`inherited_views.xml` 里的 BOM 表单项，再把 depends 去掉——**零外部影响**。

### 4.2 `website` + `lab_site`——官网副本

| 证据 | 值 |
|---|---|
| 依赖 `website` 的我们自己的模块 | 仅 `lab_site` |
| `lab_site` 做什么 | 把 Odoo 默认首页换成静态官网副本 |
| 官网真身在 | **Netlify**（`l-creation.club`，22,715 字节独立站） |
| 根域是否引用 team 子域 | **否** |

Odoo 里这份是**重复副本**。可以关。

### 4.3 `mail` / `mail_bot` / `sms` / `snailmail` / `iap*` 等通信类

| 证据 | 值 |
|---|---|
| 我们的代码调用 `message_post` / `mail.thread` | **0 处** |
| `mail_message` 394 条来源 | 全部是 Odoo 自身模型追踪（product.template 96、product.product 91、stock.lot 81…） |

我们没用它，但 `stock`/`product` 会往里写审计追踪。**关掉会丢失这些历史记录**，
且 Odoo 部分模块声明依赖它。建议保留（不影响性能）。

### 4.4 `portal` / `auth_signup` / `auth_totp` / `auth_passkey`

- `portal`：2 个 portal 用户。我们的业务不走门户。
- `auth_signup`：允许自助注册——**对内部系统是安全隐患**，建议关。
- `auth_totp` / `auth_passkey`：二次验证，可选。

### 4.5 `google_gmail` / `microsoft_outlook` / `google_recaptcha` / `social_media` /
`web_unsplash` / `partner_autocomplete` / `privacy_lookup` / `digest`

这些是 Odoo 的营销/外部集成模块，我们一个都没用。**可关**，但关掉收益有限
（它们不占资源，只是菜单里多几个入口）。

## 五、必须保留的

| 模块 | 原因 |
|---|---|
| `base` / `web` / `http_routing` / `bus` / `rpc` | Odoo 运行时本身 |
| **`stock`** | 库存真值，不可替代 |
| **`product`** / `uom` | 器件档案与计量单位 |
| **`res.users`**（属 `base`） | 账号体系 |
| `lab_*` 六个 | 我们自己的业务 |

## 六、依赖关系图（我们自己的模块）

```
lab_inventory  ← stock, product, mrp(可去)
      ↑
lab_catalog    ← base, web, stock, product, lab_inventory
      ↑
lab_workflow   ← lab_catalog, lab_inventory, stock
      ↑
lab_team_web   ← base, web, lab_catalog, lab_workflow
lab_theme      ← web
lab_site       ← website(可去)
```

## 七、建议的瘦身顺序

1. **去掉 `mrp`**：删 `mrp_bom_line.py` + BOM 表单项 + depends 里的 `mrp`。
   零风险（0 条 BOM 数据）。
2. **关掉 website 门户**：先改 nginx 挡公网（可逆）；确认官网不需要后，
   再卸 `lab_site` + `website`。
3. **关掉 `auth_signup`**：内部系统不该有自助注册入口。
4. 其余（mail/sms/portal/营销类）**建议保留**——关掉收益小，风险（依赖断裂、
   丢审计记录）反而大。

## 八、一个需要澄清的点

用户说「目前 odoo 应该只有我们写的库存管理，应该不存在说库存意外的东西」。

实际情况是：**业务逻辑确实全是我们写的**，但**数据底座是 Odoo 的
`stock`/`product`/`res.users`**——55 个模块里 49 个是 Odoo 自带，
它们是这套系统的地基，不是「意外的东西」。

真正多余的是 `mrp`（0 数据）和 `website`+`lab_site`（重复官网），
这两个可以干净地去掉。
