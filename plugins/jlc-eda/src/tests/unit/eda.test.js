import test from 'node:test';
import assert from 'node:assert/strict';
import { readPrimitive, resolveTemplateName, scanSchematic } from '../../main/eda.js';

function primitive(options = {}) {
  return {
    getState_PrimitiveType: () => options.type || 'Component',
    getState_PrimitiveId: () => options.id || 'p1',
    getState_Designator: () => options.designator || 'R1',
    getState_Name: () => options.name || '10k',
    getState_SupplierId: () => options.supplierId || '',
    getState_Supplier: () => options.supplier || '',
    getState_ManufacturerId: () => options.manufacturerId || 'MPN-1',
    getState_AddIntoBom: () => ('addIntoBom' in options ? options.addIntoBom : true),
    getState_OtherProperty: () => options.properties || {},
    getState_Footprint: () => options.footprint || { name: '0402' },
  };
}

test('resolveTemplateName resolves EDA ={Property} placeholders', () => {
  assert.equal(resolveTemplateName('={Manufacturer Part}', { 'Manufacturer Part': 'STM32F103' }, 'MPN'), 'STM32F103');
  assert.equal(resolveTemplateName('={manufacturer part}', { 'Manufacturer Part': 'ABC' }, 'MPN'), 'ABC');
  assert.equal(resolveTemplateName('={Missing}', {}, 'MPN'), 'MPN');
  assert.equal(resolveTemplateName('Plain', {}, 'MPN'), 'Plain');
});

test('readPrimitive extracts C code, name, designator, BOM flag and footprint', () => {
  const component = readPrimitive(
    primitive({
      supplierId: 'c123',
      name: '={Manufacturer Part}',
      properties: { 'Manufacturer Part': 'STM32F103C8T6' },
      designator: 'U1',
      addIntoBom: false,
    }),
  );
  assert.equal(component.code, 'C123');
  assert.equal(component.itemKey, 'lcsc:C123');
  assert.equal(component.name, 'STM32F103C8T6');
  assert.equal(component.designator, 'U1');
  assert.equal(component.addIntoBom, false);
  assert.equal(component.footprint, '0402');
});

test('readPrimitive can read C code from a named property', () => {
  const component = readPrimitive(primitive({ properties: { 'LCSC Part': 'C77' } }));
  assert.equal(component.code, 'C77');
});

test('readPrimitive never invents a code from a non-C supplier value', () => {
  const component = readPrimitive(primitive({ supplierId: 'MPN-123' }));
  assert.equal(component.code, '');
  assert.equal(component.itemKey, '');
});

test('readPrimitive ignores non-component primitives', () => {
  assert.equal(readPrimitive(primitive({ type: 'Wire' })), null);
});

test('scanSchematic loaded scope calls getAll(part,true) and warns about unloaded pages', async () => {
  let args;
  const eda = {
    sch_PrimitiveComponent: {
      getAll: async (...received) => {
        args = received;
        return [primitive({ supplierId: 'C1', designator: 'R1' }), primitive({ supplierId: '', designator: 'U1' })];
      },
    },
    dmt_Schematic: {
      getAllSchematicPagesInfo: async () => [{ name: 'p1' }, { name: 'p2' }],
    },
  };
  const result = await scanSchematic({ eda, scope: 'loaded' });
  assert.deepEqual(args, ['part', true]);
  assert.equal(result.totals.components, 2);
  assert.equal(result.totals.missingCode, 1);
  assert.ok(result.warnings.some((warning) => warning.includes('已加载图页')));
  assert.equal(result.pageInfo.total, 2);
});

test('scanSchematic page scope calls getAll(part,false)', async () => {
  let args;
  const eda = {
    sch_PrimitiveComponent: {
      getAll: async (...received) => {
        args = received;
        return [];
      },
    },
  };
  await scanSchematic({ eda, scope: 'page' });
  assert.deepEqual(args, ['part', false]);
});

test('scanSchematic selected scope filters non-components', async () => {
  const eda = {
    sch_SelectControl: {
      getAllSelectedPrimitives: async () => [
        primitive({ supplierId: 'C5', designator: 'R5' }),
        primitive({ type: 'Wire', designator: 'W1' }),
      ],
    },
  };
  const result = await scanSchematic({ eda, scope: 'selected' });
  assert.equal(result.totals.primitives, 1);
  assert.equal(result.components[0].code, 'C5');
});

test('scanSchematic explains a missing EDA context', async () => {
  await assert.rejects(() => scanSchematic({ eda: {}, scope: 'page' }), (error) => error.code === 'EDA_CONTEXT');
});
