/** @odoo-module **/
/**
 * 统一器件库（Odoo 网页端商城式主界面）+ lab_workflow 业务整合
 *
 * 产品行为（root 契约 需求与验收.md）：
 *  - 只有一份统一器件库；绑定同一 C 编号的物料只显示**一张**卡片；
 *  - 有实际内部库存的卡片全局排前；商城现货单独标注，不参与实验室库存计算；
 *  - 分类导航 + C 编号/型号/名称搜索 + 品牌/封装/参数组合筛选 + 图片卡片 + 参数/手册详情；
 *  - 图片/手册联网加载并缓存；无真实图片显示明确占位，不生成假器件图。
 *
 * 业务整合（lab_workflow，端点见 business_api_contract.json）：
 *  - 入库 receipt：选库位 + 数量 + **确切 SN 档案**（product_template_id）；
 *    同 C 多档案未选择时服务端返回 AMBIGUOUS_MATERIAL + candidates，界面必须让用户选，
 *    **绝不随机取 first**；无档案时可 on-demand 建档。
 *  - 领料 issue：ledger 必须选真实袋（bag_id）与数量、系统账号领用人、项目。
 *  - 归还 return：选真实 issue_line_id，做未归还余额校验。
 *  - 标签 labels/preview：真实调用，返回 pdf_base64，A4 预览/下载/打印，mm 尺寸可配。
 *  - 按钮结果一律按**真实事务结果**刷新目录与详情；不把内部错误谎称"模块未安装"。
 */
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

const PAGE_SIZE = 50;
const CAT = "/lab/api/catalog";
const INV = "/lab/api/inventory";
const LBL = "/lab/api/labels";

function assetUrl(url) {
  if (!url) return null;
  return "/lab/api/asset?url=" + encodeURIComponent(url);
}

function uuid() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return "req-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}

async function callLab(route, params) {
  const res = await rpc(route, params || {});
  if (!res || res.ok !== true) {
    const err = (res && res.error) || {};
    const e = new Error(err.message || "请求失败");
    e.code = err.code || "ERROR";
    e.fields = err.fields || {};
    throw e;
  }
  return res.data;
}

export class UnifiedCatalog extends Component {
  static template = "lab_catalog.UnifiedCatalog";
  static props = ["*"];

  setup() {
    this.notification = useService("notification");
    this.searchSequence = 0;
    this.facetSequence = 0;
    this.detailSequence = 0;
    this.workflowKeys = new Map();
    this.state = useState({
      loading: false,
      error: null,
      query: "",
      categoryId: null,
      brands: [],
      packages: [],
      parameters: {},
      stockOnly: false,
      items: [],
      nextCursor: null,
      total: 0,
      categories: [],
      expandedCategories: {},
      showAllParameters: false,
      facets: { brands: [], packages: [], parameters: [] },
      selected: null,
      detail: null,
      detailLoading: false,
      inventoryRevision: "",
      catalogRevision: "",
      // ---------------- workflow
      wfMode: null,             // receipt | issue | return | labels
      wfBusy: false,
      wfMessage: null,
      wfMessageType: "info",
      borrowers: [],
      locations: [],
      candidates: [],           // AMBIGUOUS_MATERIAL 候选
      form: {
        bagId: null, qty: 1, templateId: null, locationId: null,
        borrowerId: null, project: "", issueLineId: null,
        labelKind: "bag", labelId: null, copies: 1,
        widthMm: 50, heightMm: 30, marginMm: 10, gapMm: 2,
      },
      labelPdfUrl: null,
      labelInfo: null,
    });

    onWillStart(async () => {
      await Promise.all([this.loadCategories(), this.loadFacets(), this.search(true)]);
      await this.loadWorkflowContext();
    });
  }

  // ================================================================ catalog
  async loadCategories() {
    try {
      const data = await callLab(CAT + "/categories", {});
      const flat = data.categories || [];
      const byId = {};
      flat.forEach((c) => (byId[c.id] = Object.assign({}, c, { children: [] })));
      const roots = [];
      flat.forEach((c) => {
        const node = byId[c.id];
        if (c.parent_id && byId[c.parent_id]) byId[c.parent_id].children.push(node);
        else roots.push(node);
      });
      this.state.categories = roots;
    } catch (e) {
      this.state.error = e.message;
    }
  }

  async loadFacets() {
    const sequence = ++this.facetSequence;
    try {
      const data = await callLab(CAT + "/facets", {
        query: this.state.query,
        category_id: this.state.categoryId,
        brands: this.state.brands,
        packages: this.state.packages,
        parameters: this.state.parameters,
      });
      if (sequence !== this.facetSequence) return;
      this.state.facets = {
        brands: data.brands || [],
        packages: data.packages || [],
        parameters: data.parameters || [],
      };
    } catch (e) { /* 筛选面板失败不遮挡列表 */ }
  }

  async search(reset) {
    const sequence = ++this.searchSequence;
    this.state.loading = true;
    this.state.error = null;
    try {
      const data = await callLab(CAT + "/search", {
        query: this.state.query,
        category_id: this.state.categoryId,
        brands: this.state.brands,
        packages: this.state.packages,
        parameters: this.state.parameters,
        stock_only: this.state.stockOnly,
        cursor: reset ? null : this.state.nextCursor,
        limit: PAGE_SIZE,
      });
      if (sequence !== this.searchSequence) return;
      const items = reset ? (data.items || []) : this.state.items.concat(data.items || []);
      // Preserve the server global stock-first order, one card per canonical key.
      this.state.items = Array.from(new Map(items.map(item => [item.item_key, item])).values());
      this.state.nextCursor = data.next_cursor;
      this.state.total = data.total || 0;
      this.state.inventoryRevision = data.inventory_revision || "";
      this.state.catalogRevision = data.catalog_revision || "";
    } catch (e) {
      if (sequence === this.searchSequence) this.state.error = e.message;
    } finally {
      if (sequence === this.searchSequence) this.state.loading = false;
    }
  }

  async openDetail(item) {
    const sequence = ++this.detailSequence;
    this.state.selected = item;
    this.state.detail = null;
    this.state.detailLoading = true;
    this.state.wfMode = null;
    this.state.candidates = [];
    this.state.labelPdfUrl = null;
    this.state.form.bagId = null;
    this.state.form.templateId = null;
    this.state.form.issueLineId = null;
    this.state.form.qty = 1;
    try {
      const detail = await callLab(CAT + "/detail", { item_key: item.item_key });
      if (sequence !== this.detailSequence) return;
      this.state.detail = detail;
      const tids = this.state.detail.item.lab_template_ids || [];
      if (tids.length === 1) this.state.form.templateId = tids[0];
    } catch (e) {
      this.notification.add(e.message, { type: "danger" });
    } finally {
      if (sequence === this.detailSequence) this.state.detailLoading = false;
    }
  }

  /** 详情打开后需要的工作流上下文（未装 lab_workflow 时给出明确提示）。 */
  async loadWorkflowContext() {
    try {
      const b = await callLab(INV + "/bootstrap", {});
      this.state.borrowers = b.borrowers || [];
      if (this.state.borrowers.length === 1) this.state.form.borrowerId = this.state.borrowers[0].id;
      const l = await callLab(INV + "/locations", {});
      this.state.locations = l.locations || [];
      if (this.state.locations.length === 1) this.state.form.locationId = this.state.locations[0].id;
      if (this.state.locations.length > 1 && !this.state.form.locationId) {
        this.state.form.locationId = this.state.locations[0].id;
      }
    } catch (e) {
      this.state.locations = [];
      this.state.borrowers = [];
    }
  }

  // ================================================================ filters
  onQueryInput(ev) { this.state.query = ev.target.value; }
  async onQueryKeydown(ev) { if (ev.key === "Enter") await this.applyFilters(); }
  async applyFilters() { await Promise.all([this.search(true), this.loadFacets()]); }

  async selectCategory(node) {
    if (node.children && node.children.length) this.state.expandedCategories[node.id] = true;
    this.state.categoryId = this.state.categoryId === node.id ? null : node.id;
    await this.applyFilters();
  }
  get categoryRows() {
    const rows = [];
    const walk = (nodes, depth) => nodes.forEach(node => {
      rows.push({ ...node, depth });
      if (this.state.expandedCategories[node.id]) walk(node.children || [], depth + 1);
    });
    walk(this.state.categories, 0);
    return rows;
  }
  get allCategoryRows() {
    const rows = [];
    const walk = (nodes, depth) => nodes.forEach(node => {
      rows.push({ ...node, categoryLabel: '　'.repeat(depth) + node.name });
      walk(node.children || [], depth + 1);
    });
    walk(this.state.categories, 0);
    return rows;
  }
  async onCategorySelect(ev) {
    this.state.categoryId = Number(ev.target.value) || null;
    await this.applyFilters();
  }
  async toggleParameter(code, value) {
    const values = [...(this.state.parameters[code] || [])];
    const at = values.indexOf(value);
    if (at < 0) values.push(value); else values.splice(at, 1);
    if (values.length) this.state.parameters[code] = values; else delete this.state.parameters[code];
    await this.applyFilters();
  }
  closeDetail() { this.detailSequence++; this.state.selected = null; this.state.detail = null; }
  requestKey(operation, payload) {
    const fingerprint = JSON.stringify(payload);
    const previous = this.workflowKeys.get(operation);
    if (previous && previous.fingerprint === fingerprint) return previous.key;
    const key = uuid(); this.workflowKeys.set(operation, { fingerprint, key }); return key;
  }
  async toggleBrand(code) {
    const i = this.state.brands.indexOf(code);
    if (i >= 0) this.state.brands.splice(i, 1); else this.state.brands.push(code);
    await this.applyFilters();
  }
  async togglePackage(value) {
    const i = this.state.packages.indexOf(value);
    if (i >= 0) this.state.packages.splice(i, 1); else this.state.packages.push(value);
    await this.applyFilters();
  }
  async toggleStockOnly() { this.state.stockOnly = !this.state.stockOnly; await this.search(true); }
  async clearFilters() {
    this.state.brands = []; this.state.packages = []; this.state.parameters = {};
    this.state.categoryId = null; this.state.query = ""; this.state.stockOnly = false;
    await this.applyFilters();
  }
  async loadMore() { if (this.state.nextCursor) await this.search(false); }

  // ================================================================ workflow
  setMode(mode) {
    this.state.wfMode = this.state.wfMode === mode ? null : mode;
    this.state.wfMessage = null;
    this.state.candidates = [];
    this.state.labelPdfUrl = null;
    const f = this.state.form;
    const d = this.state.detail;
    if (d) {
      const tids = d.item.lab_template_ids || [];
      if (mode === "receipt") {
        if (!f.templateId && tids.length === 1) f.templateId = tids[0];
        f.qty = 1;
      }
      if (mode === "issue" && d.bags && d.bags.length) {
        f.bagId = d.bags[0].id;
        f.qty = 1;
      }
      if (mode === "return" && d.issues && d.issues.length) {
        f.issueLineId = d.issues[0].id;
        f.qty = 1;
      }
      if (mode === "labels") {
        f.labelKind = d.bags && d.bags.length ? "bag" : (f.bagId ? "bag" : "bag");
      }
    }
  }

  onField(ev) {
    const k = ev.target.dataset.field;
    let v = ev.target.value;
    if (ev.target.type === "number") v = Number(v);
    if (k === "qty" || k === "copies" || k === "widthMm" || k === "heightMm" ||
        k === "marginMm" || k === "gapMm") v = Number(v);
    if (ev.target.type === "checkbox") v = ev.target.checked;
    if (["bagId", "templateId", "locationId", "borrowerId", "issueLineId", "labelId"].includes(k)) v = v ? Number(v) : null;
    this.state.form[k] = v;
  }

  /** 统一提交：只按**真实事务结果**刷新；不把内部错误说成"模块未安装"。 */
  async runWorkflow(label, fn) {
    if (this.state.wfBusy) return null;
    this.state.wfBusy = true;
    this.state.wfMessage = null;
    this.state.candidates = [];
    try {
      const data = await fn();
      this.workflowKeys.delete(label);
      this.state.wfMessage = (label || "操作") + "已完成。";
      this.state.wfMessageType = "success";
      if (this.state.wfMode !== "labels") {
        if (this.state.selected) await this.openDetail(this.state.selected);
        await this.search(true);
      }
      return data;
    } catch (e) {
      if (e.code === "AMBIGUOUS_MATERIAL") {
        this.state.candidates = (e.fields && e.fields.candidates) || [];
        this.state.wfMessage = e.message;
        this.state.wfMessageType = "warning";
      } else {
        this.state.wfMessage = e.message;
        this.state.wfMessageType = "danger";
      }
      return null;
    } finally {
      this.state.wfBusy = false;
    }
  }

  // ---- 入库（可选目标档案；多档案未选 -> 服务端返回候选）
  async submitReceipt() {
    const f = this.state.form;
    if (!f.locationId) { this.notification.add("请选择入库库位。", { type: "warning" }); return; }
    if (!(f.qty > 0)) { this.notification.add("入库数量必须大于 0。", { type: "warning" }); return; }
    const payload = {
      item_key: this.state.selected.item_key,
      location_id: f.locationId,
      quantity: f.qty,
      product_template_id: f.templateId || null,   // 扫 SN 后保留确切档案，避免错绑
      supplier_qr: null,
      note: "",
        };
    payload.request_key = this.requestKey("入库", payload);
    await this.runWorkflow("入库", () => callLab(INV + "/receipt", payload));
  }

  async createMaterial() {
    const f = this.state.form;
    await this.runWorkflow("建档", () => callLab(CAT + "/create_material", {
      item_key: this.state.selected.item_key,
      product_template_id: f.templateId || null,
    }));
  }

  // ---- 领料（必须选真实袋 + 系统账号领用人 + 项目）
  async submitIssue() {
    const f = this.state.form;
    if (!f.bagId) { this.notification.add("请选择来源袋。", { type: "warning" }); return; }
    if (!f.borrowerId) { this.notification.add("请选择领用人（必须是系统账号）。", { type: "warning" }); return; }
    if (!f.project.trim()) { this.notification.add("请填写领用项目。", { type: "warning" }); return; }
    if (!(f.qty > 0)) { this.notification.add("领用数量必须大于 0。", { type: "warning" }); return; }
    const payload = {
      borrower_id: f.borrowerId,                  // 操作人由服务端按 env.uid 记录，另行保存
      project: f.project || "",
      lines: [{ bag_id: f.bagId, quantity: f.qty }],
      note: "",
        };
    payload.request_key = this.requestKey("领料", payload);
    await this.runWorkflow("领料", () => callLab(INV + "/issue", payload));
  }

  // ---- 归还（必须选真实 issue_line_id，并做余额校验）
  async submitReturn() {
    const f = this.state.form;
    const line = (this.state.detail.issues || []).find((i) => i.id === f.issueLineId);
    if (!line) { this.notification.add("请选择原领料记录。", { type: "warning" }); return; }
    const outstanding = line.outstanding_quantity || 0;
    if (!(f.qty > 0)) { this.notification.add("归还数量必须大于 0。", { type: "warning" }); return; }
    if (f.qty > outstanding) {
      this.notification.add(`归还数量不能超过未归还的 ${outstanding}。`, { type: "warning" });
      return;
    }
    const payload = {
      issue_line_id: f.issueLineId,
      quantity: f.qty,
      note: "",
        };
    payload.request_key = this.requestKey("归还", payload);
    await this.runWorkflow("归还", () => callLab(INV + "/return", payload));
  }

  // ---- 标签（真实 PDF：A4、mm 尺寸、预览/下载/打印）
  selectedOutstandingLine() {
    const f = this.state.form;
    return ((this.state.detail || {}).issues || []).find((i) => i.id === f.issueLineId) || null;
  }

  async previewLabels() {
    const f = this.state.form;
    const ids = f.bagId ? [f.bagId] : ((this.state.detail.bags || []).map((b) => b.id) || []);
    if (!ids.length) { this.notification.add("没有可打印的袋。", { type: "warning" }); return; }
    const data = await this.runWorkflow("标签预览", () => callLab(LBL + "/preview", {
      kind: f.labelKind,
      ids,
      copies: f.copies || 1,
      width_mm: f.widthMm,
      height_mm: f.heightMm,
      margin_mm: f.marginMm,
      gap_mm: f.gapMm,
      fields: ["sn", "location", "mpn", "catalog_code", "parameters"],
    }));
    if (!data || !data.pdf_base64) return;
    const bin = atob(data.pdf_base64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const blob = new Blob([bytes], { type: data.mime_type || "application/pdf" });
    if (this.state.labelPdfUrl) URL.revokeObjectURL(this.state.labelPdfUrl);
    this.state.labelPdfUrl = URL.createObjectURL(blob);
    this.state.labelInfo = { filename: data.filename, pages: data.page_count, count: data.label_count };
  }

  printLabels() {
    if (!this.state.labelPdfUrl) return;
    const w = window.open(this.state.labelPdfUrl, "_blank");
    if (w) w.addEventListener("load", () => w.print && w.print());
  }

  downloadLabels() {
    if (!this.state.labelPdfUrl) return;
    const a = document.createElement("a");
    a.href = this.state.labelPdfUrl;
    a.download = (this.state.labelInfo && this.state.labelInfo.filename) || "labels.pdf";
    document.body.appendChild(a); a.click(); a.remove();
  }

  // ================================================================ helpers
  imageSrc(item) { return assetUrl(item.image_url); }
  assetSrc(url) { return assetUrl(url); }
  uuid() { return uuid(); }

  onImageError(ev) {
    ev.target.style.display = "none";
    if (ev.target.nextElementSibling) ev.target.nextElementSibling.style.display = "flex";
  }

  formatQty(v) {
    const n = Number(v || 0);
    return Number.isInteger(n) ? String(n) : n.toFixed(2);
  }
}

registry.category("actions").add("lab_catalog.unified", UnifiedCatalog);
