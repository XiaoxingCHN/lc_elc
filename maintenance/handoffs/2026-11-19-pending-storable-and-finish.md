# 维护交接：新建器件不可入库 + 制袋贴标补完成按钮

- 分支：`feat/receipt-param-search`（工作树 `.claude/worktrees/read-tomc-memory-56e7a2`）
- 未提交；**服务端修复未部署**。

## 用户反馈（截图）

扫码上架时报错：

```
物料「GH1.25 端子 2P」当前未开启库存管理（is_storable=False）。
入库前请先开启，或在物料表单勾选「跟踪库存」。
```

并指出「我制袋贴标没有完成按钮」。

## 一、服务端 bug（这是真 bug，不是操作问题）

`lab_pending_receipt.py` 的 `_lab_pending_create_once` 里，「新建器件」分支建
`product.template` 时**只给了 name/type/lab_* 字段，漏了 `is_storable` 与 `tracking`**：

```python
template = self.env['product.template'].sudo().create({
    'name': ..., 'type': 'consu', ...   # ← 没有 is_storable, 没有 tracking
})
```

Odoo 19 里 `type='consu'` 但 `is_storable=False` 的模板**不可库存**，且
`tracking` 会被 `_compute_tracking` 强制回 `'none'`。于是：

1. 制袋码能正常生成（这一步不校验库存能力）；
2. 到「扫码上架」确认时走 `lab_pending_confirm → _lab_receipt_once →
   lab_ensure_storable_tracking`，被 `is_storable=False` 直接拒绝。

**其它建档路径都设了这两项**（`_lab_create_minimal_material` 在
`lab_workflow_common.py:623`、资料库绑定 `catalog_api.py:446`），只有这一条漏了。

修法：补 `'is_storable': True, 'tracking': 'lot'`，与其它路径一致。

测试 `test_pending_create_key_replay_and_manual_archive` 增断言：
手工建档的模板必须 `is_storable` 且 `tracking == 'lot'`，并且**能真正入库**
（`lab_pending_confirm` 后数量 0 → 20）。这条断言就是为了让「能建袋码但不能入库」
这个组合不再可能。

### 部署

`lab_workflow` 版本 `19.0.2.0.3 → 19.0.2.0.4`。**这是生产写入**，需要授权后在服务器上：

```
server/ubuntu22.04/upgrade_modules.sh lab_workflow
```

未部署前，旧服务器仍会拒绝手工建档物料的入库。已在界面上能避开：
选器件时走「从器件库选择」/立创抓取（这些路径的模板是可库存的）。

## 二、制袋贴标没有完成按钮

这一页原本结束在「预览并打印（N 袋）」上：

- 打印完不告诉操作员这一步结束了；
- 没有任何进入下一步的入口（页签 2 只能靠顶部切换器点）。

新增收尾区「第 1 步 · 制袋贴标」，含：

- 当前勾选袋数说明（0 袋时提示「生成袋码后在每一条上勾选『加入待打印』」）；
- 「预览并打印（N 袋）」；
- **「完成贴标，进入『扫码上架』」**：切到页签 2，并清空上一袋的核对状态
  （`_resolved`/`_recommendations`/`_locationId` 置空、`_scanCycle++` 重建扫码框）。

## 实测

- `flutter test --no-pub` → **504 passed / 5 skipped / 0 failed**。
- `flutter analyze --no-pub lib test` → 0 error / 0 warning。
- 服务端改动 `python -m py_compile` 通过。
- Windows 1.3.5+20 三步 exit 0；Android 1.3.5+20 三步 exit 0（APK 证书与登记一致）。
- `python tools/repo_check.py` → **PASS 53 项**。

## 产物

| 平台 | 文件 | 大小 | sha256 |
|---|---|---|---|
| Windows | `clients/windows/releases/1.3.5+20/LC_ELC-Windows-1.3.5+20-x64.zip` | 37,734,716 B | `6fcc3d25…a4eed6` |
| Android | `clients/android/releases/1.3.5+20/LC_ELC-Android-1.3.5+20.apk` | 108,025,712 B | `9a31d0a0…0eb5ff` |

清单：`source-client-1.3.5-20-20261119.json`（220 文件）、
`source-server-pending-storable-20261119.json`（274 文件），均已 `--activate`。

## 未验证

- **服务端 Odoo 测试本机跑不了**（Windows 上没有 Odoo 运行时）。`test_workflow_business.py`
  的新断言必须在服务器上跑：`python3 -m odoo -d <db> --test-tags /lab_workflow:TestWorkflowBusiness --stop-after-init`。
- 服务端未部署，旧服务器行为不变。
- 已在库里存在的 `is_storable=False` 物料**不会**被这次修复自动改正（修复只影响新建）。
  若现网还有这类物料，需要单独处理：要么在 Odoo 物料表单勾选「跟踪库存」，
  要么走「历史库存分袋适配」。
- Android 实机、真实打印与扫码未验证。
- 未 commit / 未 push。
