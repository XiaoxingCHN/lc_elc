# -*- coding: utf-8 -*-
"""P3 其余自有业务页（issue / inventory / account）交互一致性静态契约。

只读断言，不需要 Odoo 运行时：
- 面向普通用户的文案里不再出现技术字段口径（领用明细 ID / PRECONDITION_FAILED / internal / lcsc: 前缀示例）；
- 每张表头都带 scope="col"（窄屏卡片化与屏幕阅读器都依赖）；
- 流水筛选按"袋码"而不是数据库 id 收输入；
- 窄屏卡片化依赖的 data-label 与 44px 触控下限在源码里确实存在。

注意：这是静态契约，不代表浏览器里已渲染通过（视觉与零宽断言另见交接里的未覆盖项）。
"""

import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

MODULE = Path(__file__).resolve().parent.parent
VIEWS = MODULE / "views"
JS = MODULE / "static" / "src" / "js" / "pages"
CSS = MODULE / "static" / "src" / "css"

MY_VIEWS = ("workflow_issue.xml", "workflow_inventory.xml", "workflow_account.xml")


def read(path):
    return path.read_text(encoding="utf-8")


def css_preludes(text):
    """返回一段 CSS 里所有规则的选择器（跳过注释与 @media 等 at-rule 说明）。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    preludes = []
    buf = []
    for ch in text:
        if ch == "{":
            selector = "".join(buf).strip()
            buf = []
            if selector and not selector.startswith("@"):
                preludes.append(selector)
        elif ch == "}":
            buf = []
        else:
            buf.append(ch)
    return preludes


class ViewWordingTest(unittest.TestCase):
    def test_views_are_well_formed_xml(self):
        for name in MY_VIEWS:
            with self.subTest(view=name):
                ET.parse(str(VIEWS / name))

    def test_no_issue_line_id_column_for_operators(self):
        text = read(VIEWS / "workflow_issue.xml")
        self.assertNotIn("领用明细 ID</th>", text)
        self.assertNotIn("领用明细 ID", text.split("<template id=\"workflow_issue_history\"")[0])

    def test_history_filters_take_bag_code_not_database_id(self):
        text = read(VIEWS / "workflow_issue.xml")
        self.assertIn('name="bag_code"', text)
        self.assertNotIn('name="bag_id"', text)

    def test_inventory_uses_human_wording(self):
        text = read(VIEWS / "workflow_inventory.xml")
        self.assertNotIn("PRECONDITION_FAILED", text)
        self.assertNotIn('lc-mono">internal<', text)
        self.assertIn("前置条件未满足", text)

    def test_every_table_header_has_scope(self):
        for name in MY_VIEWS:
            text = read(VIEWS / name)
            with self.subTest(view=name):
                for match in re.finditer(r"<th\b[^>]*>", text):
                    self.assertIn('scope="col"', match.group(0))


class PageScriptTest(unittest.TestCase):
    def test_history_normalises_user_input(self):
        text = read(JS / "history.js")
        self.assertIn("function resolveItemKey", text)
        self.assertIn("function resolveBagId", text)
        self.assertIn("ITEM_PREFIX_RE", text)
        self.assertIn("data-label", text)

    def test_materials_binding_has_change_feedback_and_consistency_check(self):
        text = read(JS / "materials.js")
        self.assertIn("function onTemplateChange", text)
        self.assertIn("addEventListener('change', onTemplateChange)", text)
        self.assertIn("所选档案已不在当前下拉里", text)

    def test_inventory_pages_copy_headers_to_cells(self):
        for name in ("locations.js", "mappings.js", "settings.js", "materials.js"):
            text = read(JS / name)
            with self.subTest(page=name):
                self.assertIn("function labelCells", text)
                self.assertIn("labelCells();", text)
                self.assertIn("data-lc-table=", text)

    def test_issue_pages_label_cells_and_drop_technical_column(self):
        text = read(JS / "issue_new.js")
        self.assertIn("data-label", text)
        self.assertNotIn("issue_line_id)", text)
        self.assertIn("data-label", read(JS / "issues.js"))


class InteractionRegressionTest(unittest.TestCase):
    """本轮回归：375 单元格值消失 / 角色勾选框 22px / 流水关键词承诺。"""

    def test_issue_stacked_selectors_beat_team_css_min_width(self):
        """窄屏堆叠规则必须以 body.lc-body 开头。

        team.css 里 `body.lc-body .lc-table-wrap .lc-table { min-width: 560px }`
        的特异度是 (0,3,1)；如果本文件只写 `.lc-workflow .lc-table[...]`（0,3,0），
        min-width:0 不生效，表格仍被撑到 560px，窄屏卡片里的值会被挤出卡外
        —— 375 实测「只有标签没有值」就是这么来的。
        """
        text = read(CSS / "workflow_issue.css")
        block = text.split("@media (max-width: 760px)")[-1]
        selectors = css_preludes(block)
        self.assertTrue(selectors, "760px 媒体查询里没有找到选择器")
        offenders = [
            sel.strip() for sel in selectors
            if not sel.strip().startswith("body.lc-body")
        ]
        self.assertEqual(offenders, [], "这些窄屏选择器缺少 body.lc-body 前缀")
        self.assertIn("min-width: 0", block)

    def test_role_checkbox_hit_target_is_44px_label(self):
        js = read(JS / "settings.js")
        self.assertIn("lc-inv-role-hit", js, "settings.js 没把角色勾选框包进 label")
        css = read(CSS / "workflow_inventory.css")
        hit = re.search(
            r"\.lc-inv-role-hit\s*\{[^}]*\}", css)
        self.assertIsNotNone(hit, "workflow_inventory.css 没有 .lc-inv-role-hit 规则")
        self.assertIn("min-width: 44px", hit.group(0))
        self.assertIn("min-height: 44px", hit.group(0))

    def test_history_filter_does_not_promise_keyword_search(self):
        """/lab/api/inventory/resolve_code 只认袋码/库位码/SN/立创 C 码/原厂袋码。

        流水页的「器件」框不能承诺按名称或型号关键词搜索。说明允许放在
        可展开的 details 里（一行提示 + 展开详情），所以这里只要求整页写着
        「不支持按名称」，且不再把长说明塞进控件单元（否则 4 列网格会参差）。
        """
        xml = read(VIEWS / "workflow_issue.xml")
        self.assertIn("不支持按名称", xml, "筛选提示必须写明不支持关键词搜索")
        field = xml.split('name="item_key"')[1].split("</div>")[0]
        self.assertNotIn("lc-hint", field, "长说明不要再塞进器件输入框的单元里")
        js = read(JS / "history.js")
        self.assertIn("不支持按名称/型号关键词搜索", js)
        self.assertIn("function notFoundItem", js)
        self.assertIn("function notFoundBag", js)

    def test_history_filter_uses_aligned_grid(self):
        """流水筛选：网格对齐 + 说明可展开。

        team.css 的 .lc-toolbar 是 flex + align-items:center，字段高度不同时
        标签会被垂直居中错层。这里锁住：筛选用 grid、按钮作为网格项底对齐、
        长说明在 <details class="lc-help"> 里（team.css 已有该组件样式）。
        """
        xml = read(VIEWS / "workflow_issue.xml")
        self.assertIn('class="lc-history-grid"', xml)
        self.assertIn('class="lc-history-actions"', xml)
        self.assertIn('<details class="lc-help lc-history-help">', xml)
        self.assertIn("<summary>", xml)
        css = read(CSS / "workflow_issue.css")
        grid = re.search(r"\.lc-history-grid\s*\{[^}]*\}", css)
        self.assertIsNotNone(grid, "workflow_issue.css 没有 .lc-history-grid 规则")
        self.assertIn("display: grid", grid.group(0))
        actions = re.search(r"\.lc-history-actions\s*\{[^}]*\}", css)
        self.assertIsNotNone(actions, "workflow_issue.css 没有 .lc-history-actions 规则")
        self.assertIn("align-self: end", actions.group(0))
        # 必须带 body.lc-body 前缀，否则压不过 team.css 的 body.lc-body .lc-toolbar
        self.assertIn("body.lc-body .lc-workflow .lc-history-filter", css)


class NarrowScreenCssTest(unittest.TestCase):
    def test_issue_css_stacks_tables(self):
        text = read(CSS / "workflow_issue.css")
        self.assertIn('data-lc-table="cart"', text)
        self.assertIn('data-lc-table="history"', text)
        self.assertIn("content: attr(data-label)", text)

    def test_inventory_css_stacks_tables_and_meets_touch_target(self):
        text = read(CSS / "workflow_inventory.css")
        self.assertIn('data-lc-table="members"', text)
        self.assertIn('data-lc-table="materials"', text)
        self.assertIn("content: attr(data-label)", text)
        # 小按钮的触控下限：≤560px 与 ≤760px 两处都必须 ≥44px（.lc-inv-btn-sm 不得缩小）
        self.assertIn("min-height: 44px", text)
        self.assertIn(".lc-inv-btn-sm", text)
        self.assertIn("@media (any-pointer: coarse)", text)


if __name__ == "__main__":
    unittest.main()

class SharedUiContractTest(unittest.TestCase):
    """共享 UI（入库/标签/导航）第三轮回归：真实缺陷的静态锁。

    每一条都对应 root 真实浏览器报告里的一个 fail，改坏就会红：
    - 表格里的勾选框命中区（13px -> 44px）；
    - settings / mappings 过滤勾选的命中区（26/34px -> 44px）；
    - 建袋提交必须读"下拉真实选中值"，不能只认 form.elements；
    - 入库页可见文案不出现实现字段名；
    - 标签页签的 tab/panel ARIA 与 roving tabindex；
    - 窄屏抽屉的焦点循环与背景 inert 覆盖账号区。
    """

    def test_table_checkboxes_have_44px_hit_area(self):
        for name in ("receipts.js", "labels.js"):
            with self.subTest(script=name):
                text = read(JS / name)
                self.assertIn("lc-cell-check", text)
                self.assertIn("lc-check lc-check-cell", text)
        css = read(CSS / "team.css")
        self.assertRegex(
            css, r"\.lc-check\.lc-check-cell\s*\{[^}]*min-width:\s*44px",
            "表格勾选的命中区必须 44px 宽")
        self.assertRegex(
            css, r"\.lc-check\.lc-check-cell\s*\{[^}]*min-height:\s*44px",
            "表格勾选的命中区必须 44px 高")
        self.assertRegex(css, r"\.lc-table td\.lc-cell-check\s*\{")

    def test_inventory_filter_checkboxes_use_44px_label(self):
        text = read(VIEWS / "workflow_inventory.xml")
        for anchor in ("lc-inv-map-inactive", "lc-inv-map-active", "lc-inv-mem-only-role"):
            with self.subTest(anchor=anchor):
                self.assertIn('class="lc-check" for="%s"' % anchor, text)
                self.assertNotIn('class="lc-inline" for="%s"' % anchor, text)

    def test_create_submit_reads_select_control_value(self):
        text = read(JS / "receipts.js")
        # 下拉在 <form> 之外，formValues() 取不到；提交值必须来自控件本身。
        self.assertIn("slot('material-select')", text)
        self.assertIn("selectNode.value", text)
        self.assertNotIn("LC.parse.int(values.product_template_id", text)

    def test_receipt_visible_copy_has_no_backend_field_names(self):
        raw = read(VIEWS / "workflow_receipt.xml")
        visible = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
        for word in ("stock.quant", "pending/update", "Odoo", "服务端"):
            with self.subTest(word=word):
                self.assertNotIn(word, visible)

    def test_labels_tabs_have_aria_and_roving_tabindex(self):
        raw = read(VIEWS / "workflow_receipt.xml")
        for kind in ("pending", "bag", "location"):
            with self.subTest(kind=kind):
                self.assertIn('id="lc-tab-kind-%s"' % kind, raw)
                self.assertIn('aria-controls="lc-panel-labels"', raw)
        self.assertIn('id="lc-panel-labels" role="tabpanel"', raw)
        self.assertIn('aria-labelledby="lc-tab-kind-pending"', raw)
        script = read(JS / "labels.js")
        self.assertIn("setAttribute('tabindex'", script)
        self.assertIn("setAttribute('aria-labelledby'", script)
        self.assertIn('[role="tablist"]', script)

    def test_drawer_traps_focus_and_inerts_account(self):
        text = read(MODULE / "static" / "src" / "js" / "team.js")
        for bg in (".lc-footer", ".lc-account", ".lc-brand"):
            with self.subTest(backdrop=bg):
                self.assertIn(bg, text)
        self.assertIn("trapTargets", text)
        self.assertIn("event.key !== 'Tab'", text)

    def test_business_error_shows_server_actionable_text(self):
        """业务前置条件的可执行说明只在服务端 message 里（例如「请先做历史库存分袋适配」）。

        通用句（PRECONDITION_FAILED → 当前条件不满足）会把它盖掉，等于让用户无从下手；
        所以 core 的 errorText 对已知业务码优先用服务端人话，且只放行含中文的说明，
        纯字段名/异常名仍退回通用句；INTERNAL_ERROR 仍带错误编号。
        """
        core = read(MODULE / "static" / "src" / "js" / "workflow_core.js")
        self.assertIn("SERVER_TEXT_CODES", core)
        self.assertIn("HAS_HUMAN_TEXT", core)
        for code in ("VALIDATION_ERROR", "PRECONDITION_FAILED", "CONFLICT", "DUPLICATE_REQUEST"):
            with self.subTest(code=code):
                self.assertIn("%s: true" % code, core)
        self.assertIn("'（错误编号 '", core)
        # 页面侧不再各自判断，统一走 core（单一口径，避免有的页吞掉服务端说明）
        self.assertIn("message: LC.errorText(err),", read(JS / "receipts.js"))


if __name__ == "__main__":
    unittest.main()
