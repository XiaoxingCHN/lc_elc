# 任务：剥离门户与冗余模块，后台管理改为自有 UI

- Status: approved-in-principle（用户已确认方向，待分批执行）
- 用户原话：
  > 确认 odoo 提供的对外门户网站我们是不需要的，我们只需要依赖 odoo 的库存管理相关的
  > 模块…然后我们并不想继续使用 odoo 原生后台 UI 来管理整个账户和库存相关的一是不统一，
  > 二是门户太乱不好管理，只需要提供一个特定入口或者是只有管理员账号登录时才有完全管理的界面

## 一、依赖边界（已用 SQL 递归算出）

### 必须保留的闭包（17 个）

```
auth_signup  barcodes  barcodes_gs1_nomenclature  base  base_setup  bus
digest  html_editor  http_routing  mail  portal  product  resource
stock  uom  web  web_tour
```

加上我们自己的 5 个（`lab_site` 不在内）：
`lab_workflow`、`lab_catalog`、`lab_inventory`、`lab_team_web`、`lab_theme`

**共 22 个模块**。

> 注：`auth_signup` 和 `portal` 在 `stock` 的闭包里（`stock` → `portal` → `auth_signup`），
> 不能单独卸。但可以在 nginx 层挡掉 `/web/signup`、`/my/*`，效果等同于关闭。

### 可以卸载的（32 个）

```
api_doc  auth_passkey  auth_passkey_portal  auth_totp  auth_totp_mail
auth_totp_portal  base_import  base_import_module  base_install_request
google_gmail  google_recaptcha  html_builder  iap  iap_mail  lab_site
mail_bot  microsoft_outlook  partner_autocomplete  phone_validation
privacy_lookup  resource_mail  rpc  sms  snailmail  social_media
stock_sms  theme_default  utm  web_unsplash  website  website_mail  website_sms
```

其中 **`mrp` 要单独处理**：它不在可卸载列表里（因为 `lab_inventory` 依赖它），
但我们已经确认 `mrp_bom` 表 0 条记录、`lab_allocation` 全空。做法：
先改 `lab_inventory/__manifest__.py` 去掉 `mrp` 依赖并删掉 `mrp_bom_line.py`，
升级后再卸 `mrp`。

## 二、分三批执行

### 批次 1：去 mrp + 关门户（零风险，先做）

1. `lab_inventory`：删 `models/mrp_bom_line.py`、`models/__init__.py` 里的 import、
   `views/inherited_views.xml` 里的 BOM 表单项、`__manifest__.py` 的 `mrp` 依赖；
2. `lab_site`：整个模块标记为待卸（保留源码，生产卸载）；
3. 卸载 `mrp`、`website`、`website_mail`、`website_sms`、`lab_site`、`theme_default`；
4. nginx 现役 18443 vhost 加规则：`/`、`/about-us`、`/contactus`、`/website/*`
   返回 404 或 301 → `/team/login`。

**回滚**：数据库备份 + 模块可重装。

### 批次 2：管理员专用入口（核心诉求）

用户要的「只有管理员账号登录时才有完全管理的界面」。

**方案：新增 `/team/admin` 管理台**，只在 `group_lab_manager` 或
`base.group_system` 可见。分三块：

| 区块 | 覆盖的后台任务 | 需要的新端点 |
|---|---|---|
| 账号 | 建用户、改密码、停用、系统权限组 | `user_create`、`user_set_password`、`user_toggle_active`、`user_set_system_group` |
| 器件 | 产品编辑、分类树 | `product_update`、`category_create/update/delete` |
| 库存 | 盘点、报废、库位调拨 | `stock_adjust`（**必须走 `stock.move`**） |

**关键约束**：库存调整只能通过 `stock.move` + `_action_done()`（沿用
`lab_workflow_common._lab_move` 的既有通道），**绝不直接写 `stock.quant`**，
且需要二次确认 + 审计日志。

### 批次 3：清理剩余模块

卸载批次 1 之外的那 27 个（`sms`/`snailmail`/`iap*`/营销类/`web_unsplash` 等）。

**风险评估**：这些模块卸载会删掉它们自己的数据表（如 `sms_sms`）。
我们的代码不依赖它们，但 `stock`/`product` 可能写了 `mail_message` 记录。
建议先备份，再卸，卸完验证库存与流水完整。

## 三、验收标准

1. `ir_module_module` 里 `installed` 的模块数从 55 降到 22–25；
2. 公网 `https://team.l-creation.club/` 不再是 Odoo 网站页；
3. `/team/*`、`/lab/*`、客户端 API 全部正常；
4. 入库/领料/归还/盘点/报废全部走 `stock.move`，`stock.quant` 与流水一致；
5. 管理员在 `/team/admin` 能建账号、改密码、编辑产品、做盘点；
6. 非管理员看不到 `/team/admin`（403）。

## 四、风险

1. **卸载模块不可逆**（数据表会被删）。每批卸载前必须做数据库备份。
2. **`stock` 闭包里的 `portal`/`auth_signup` 卸不掉**，只能 nginx 挡路径。
3. **批次 3 的 27 个模块**：逐个确认没有隐藏依赖再卸，不要批量。
4. **库存调整是最危险的功能**：建议批次 2 里最后做，且先只做「盘点」不做「报废」。

## 五、待确认

1. 公网 `/` 关掉后：404 还是 301 → `/team/login`？
2. 批次 3 要不要做？（27 个模块卸载，收益是「后台干净」，风险是数据表删除）
