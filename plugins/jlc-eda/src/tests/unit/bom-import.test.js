import test from 'node:test';
import assert from 'node:assert/strict';
import { parseBomCsv, parseCsvRows, allocateBags } from '../../shared/bom.js';

const SAMPLE = [
  'No.,Quantity,Comment,Designator,Footprint,Supplier Part,Manufacturer Part',
  '1,2,10k,R1 R2,0402,C25804,RC0402FR-0710KL',
  '2,1,100nF,C1,0402,C1525,CL05B104KO5NNNC',
  '3,1,STM32,U1,LQFP48,,STM32F103C8T6',
  '4,1,"Reserved, DNP",R9,0603,C25804,RC0603',
].join('\r\n');

test('parseCsvRows handles quotes, commas and CRLF', () => {
  const rows = parseCsvRows('a,"b,c","d""e"\r\n1,2,3\n');
  assert.deepEqual(rows, [
    ['a', 'b,c', 'd"e'],
    ['1', '2', '3'],
  ]);
});

test('parseBomCsv groups rows by C code and sums quantity', () => {
  const result = parseBomCsv(SAMPLE);
  const codes = result.lines.map((line) => line.code).sort();
  assert.deepEqual(codes, ['C1525', 'C25804']);
  const resistor = result.lines.find((line) => line.code === 'C25804');
  assert.equal(resistor.quantity, 3);
  assert.deepEqual(resistor.designators.sort(), ['R1', 'R2', 'R9']);
  assert.equal(resistor.mpn, 'RC0402FR-0710KL');
  assert.equal(result.unmapped.length, 1);
  assert.equal(result.unmapped[0].designator, 'U1');
  assert.equal(result.lines.find((line) => line.code === 'C1525').quantity, 1);
});

test('parseBomCsv recognises Chinese headers', () => {
  const csv = ['序号,数量,名称,位号,封装,立创编号', '1,4,电容,C1 C2 C3 C4,0402,C1525'].join('\n');
  const result = parseBomCsv(csv);
  assert.equal(result.lines.length, 1);
  assert.equal(result.lines[0].code, 'C1525');
  assert.equal(result.lines[0].quantity, 4);
  assert.deepEqual(result.lines[0].designators, ['C1', 'C2', 'C3', 'C4']);
});

test('parseBomCsv reports an unusable header instead of guessing', () => {
  const result = parseBomCsv('foo,bar\n1,2');
  assert.equal(result.lines.length, 0);
  assert.ok(result.warnings[0].includes('无法识别 BOM 表头'));
});

test('parseBomCsv drops rows explicitly excluded from BOM', () => {
  const csv = ['Quantity,Designator,Supplier Part,Add into BOM', '1,R1,C1,yes', '2,R2,C2,no'].join('\n');
  const result = parseBomCsv(csv);
  assert.equal(result.lines.length, 1);
  assert.equal(result.lines[0].quantity, 1);
  assert.equal(result.excluded, 2);
});

test('allocateBags takes bags FIFO and never invents stock', () => {
  const bags = [
    { id: 9, available_quantity: null, trace_code: 'x' },
    { id: 3, available_quantity: 1 },
    { id: 7, available_quantity: 5 },
    { id: 1, available_quantity: 0 },
  ];
  const allocation = allocateBags(bags, 4);
  assert.deepEqual(allocation.lines, [
    { bag_id: 3, quantity: 1 },
    { bag_id: 7, quantity: 3 },
  ]);
  assert.equal(allocation.shortfall, 0);
  assert.equal(allocation.need, 4);
});

test('allocateBags reports the shortfall when bags cannot cover the need', () => {
  const allocation = allocateBags([{ id: 2, available_quantity: 2 }], 5);
  assert.deepEqual(allocation.lines, [{ bag_id: 2, quantity: 2 }]);
  assert.equal(allocation.shortfall, 3);
});

test('allocateBags ignores bags without a usable available quantity', () => {
  const allocation = allocateBags([{ id: 1 }, { id: 2, available_quantity: '0' }, { id: 3, available_quantity: 2 }], 2);
  assert.deepEqual(allocation.lines, [{ bag_id: 3, quantity: 2 }]);
  assert.equal(allocation.shortfall, 0);
});
