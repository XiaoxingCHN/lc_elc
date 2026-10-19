import test from 'node:test';
import assert from 'node:assert/strict';
import { scanProjectBom, withTimeout } from '../../main/eda.js';

const CSV = ['Quantity,Designator,Supplier Part,Comment', '2,R1 R2,C25804,10k'].join('\n');

function primitive() {
  return {
    getState_PrimitiveType: () => 'Component',
    getState_PrimitiveId: () => 'p1',
    getState_Designator: () => 'R1',
    getState_Name: () => '10k',
    getState_SupplierId: () => 'C1',
    getState_Supplier: () => '',
    getState_ManufacturerId: () => '',
    getState_AddIntoBom: () => true,
    getState_OtherProperty: () => ({}),
    getState_Footprint: () => '0402',
  };
}

test('withTimeout rejects a hanging promise with a readable message', async () => {
  await assert.rejects(() => withTimeout(new Promise(() => {}), 60, 'demo.call'), (error) => {
    assert.equal(error.code, 'EDA_CONTEXT');
    assert.match(error.message, /demo\.call 超过/);
    return true;
  });
});

test('scanProjectBom prefers the schematic BOM export in the schematic editor', async () => {
  let pcbCalled = false;
  const eda = {
    sch_PrimitiveComponent: { getAll: async () => [] },
    sch_ManufactureData: { getBomFile: async () => ({ text: async () => CSV }) },
    pcb_ManufactureData: {
      getBomFile: async () => {
        pcbCalled = true;
        throw new Error('pcb must not be used');
      },
    },
  };
  const result = await scanProjectBom({ eda });
  assert.equal(result.source, 'bom');
  assert.equal(result.provider, 'sch_ManufactureData');
  assert.equal(result.lines.length, 1);
  assert.equal(result.lines[0].code, 'C25804');
  assert.equal(result.lines[0].quantity, 2);
  assert.equal(pcbCalled, false);
});

test('scanProjectBom falls back to the schematic scan when the export hangs', async () => {
  const eda = {
    sch_PrimitiveComponent: { getAll: async () => [primitive()] },
    sch_ManufactureData: { getBomFile: () => new Promise(() => {}) },
  };
  const started = Date.now();
  const result = await scanProjectBom({ eda, timeoutMs: 80 });
  const elapsed = Date.now() - started;
  assert.equal(result.source, 'schematic');
  assert.equal(result.scope, 'project');
  assert.ok(result.components.length >= 1, 'falls back to real schematic components');
  assert.ok(elapsed < 5000, 'bounded timeout, took ' + elapsed + 'ms');
  assert.match(result.bomError.message, /没有返回/);
  assert.ok(result.warnings.some((warning) => warning.includes('已改用原理图读取')));
});

test('scanProjectBom surfaces an explicit error when no BOM API exists', async () => {
  const eda = { sch_PrimitiveComponent: { getAll: async () => [] } };
  const result = await scanProjectBom({ eda });
  assert.equal(result.source, 'schematic');
  assert.match(result.bomError.message, /没有 BOM 导出接口/);
});
