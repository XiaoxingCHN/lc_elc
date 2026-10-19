import test from 'node:test';
import assert from 'node:assert/strict';
import { groupBom, compareLine, summarize, bomTsv, BOM_STATUS } from '../../shared/bom.js';

const components = [
  { designator: 'R1', code: 'C1', name: '10k', addIntoBom: true },
  { designator: 'R2', code: 'C1', name: '10k', addIntoBom: true },
  { designator: 'C1', code: 'C2', name: '100nF', addIntoBom: true },
  { designator: 'D1', code: 'C2', name: '100nF', addIntoBom: false },
  { designator: 'U1', code: '', name: 'No code', addIntoBom: true },
  { designator: 'U2', code: 'C0', name: 'Invalid code', addIntoBom: true },
  { designator: 'X1', code: 'C3', name: 'Flag unknown', addIntoBom: null },
];

test('groupBom merges only valid C codes and honors AddIntoBom', () => {
  const result = groupBom(components);
  assert.equal(result.lines.length, 3);
  assert.equal(result.bomComponents, 4);
  const c1 = result.lines.find((line) => line.code === 'C1');
  assert.equal(c1.quantity, 2);
  assert.deepEqual(c1.designators, ['R1', 'R2']);
  assert.equal(result.excluded.length, 1);
  assert.equal(result.unmapped.length, 2);
  assert.equal(result.lines.find((line) => line.code === 'C2').quantity, 1);
  assert.equal(result.lines.find((line) => line.code === 'C3').quantity, 1);
});

test('groupBom can include non-BOM components when asked', () => {
  const result = groupBom(components, { bomOnly: false });
  assert.equal(result.lines.find((line) => line.code === 'C2').quantity, 2);
  assert.equal(result.excluded.length, 0);
});

test('compareLine reports ok, short, unknown and not-in-catalog without inventing 0', () => {
  const line = { code: 'C1', itemKey: 'lcsc:C1', quantity: 2, designators: ['R1'], locations: [] };
  const ok = compareLine(line, {
    item: { lab_available_quantity: 5, lab_quantity: 8 },
    locations: [{ location: 'R01', available_quantity: 5 }],
    bags: [{ id: 1 }],
    lab_templates: [{ id: 1 }],
  });
  assert.equal(ok.status, BOM_STATUS.OK);
  assert.equal(ok.available, 5);
  assert.equal(ok.gap, 0);

  const short = compareLine(line, { item: { lab_available_quantity: 1, lab_quantity: 3 } });
  assert.equal(short.status, BOM_STATUS.SHORT);
  assert.equal(short.gap, 1);

  const unknown = compareLine(line, { item: { lab_available_quantity: null, lab_quantity: null } });
  assert.equal(unknown.status, BOM_STATUS.UNKNOWN);
  assert.equal(unknown.available, null);
  assert.equal(unknown.gap, null);

  const notFound = compareLine(line, null, { code: 'NOT_FOUND', message: 'missing' });
  assert.equal(notFound.status, BOM_STATUS.NOT_IN_CATALOG);
  assert.equal(notFound.gap, null);

  const failed = compareLine(line, null, { code: 'NETWORK_OR_CORS', message: 'down' });
  assert.equal(failed.status, BOM_STATUS.UNKNOWN);
  assert.equal(failed.detailError.code, 'NETWORK_OR_CORS');
});

test('summarize counts known totals separately from unknown lines', () => {
  const rows = [
    { need: 2, available: 5, gap: 0, status: BOM_STATUS.OK },
    { need: 3, available: 1, gap: 2, status: BOM_STATUS.SHORT },
    { need: 1, available: null, gap: null, status: BOM_STATUS.UNKNOWN },
    { need: 1, available: null, gap: null, status: BOM_STATUS.NOT_IN_CATALOG },
  ];
  const summary = summarize(rows);
  assert.equal(summary.need, 7);
  assert.equal(summary.available, 6);
  assert.equal(summary.gap, 2);
  assert.equal(summary.shortLines, 1);
  assert.equal(summary.unknownLines, 1);
  assert.equal(summary.notInCatalogLines, 1);
  assert.equal(summary.okLines, 1);
});

test('bomTsv marks unknown stock explicitly', () => {
  const tsv = bomTsv([
    {
      status: BOM_STATUS.UNKNOWN,
      code: 'C9',
      name: 'X',
      mpn: 'M',
      designators: ['U1'],
      need: 1,
      available: null,
      gap: null,
      locations: [],
    },
  ]);
  assert.match(tsv, /未知/);
  assert.match(tsv, /C9/);
});

test('real grouped BOM retains demand through comparison, totals and TSV',()=>{
 const grouped=groupBom(['R1','R2','R3'].map(designator=>({designator,code:'C2040',addIntoBom:true})));
 const rows=grouped.lines.map(line=>compareLine(line,{item:{lab_available_quantity:2,lab_quantity:2}}));
 assert.equal(rows[0].need,3);assert.equal(summarize(rows).need,3);assert.equal(rows[0].gap,1);assert.match(bomTsv(rows),/\t3\t2\t1\t/);
});
