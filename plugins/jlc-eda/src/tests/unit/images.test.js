import test from 'node:test';
import assert from 'node:assert/strict';
import { toOdooAssetUrl, bytesToBase64, createImageLoader } from '../../main/images.js';

test('external mall image is converted to the existing Odoo asset proxy', () => {
  const url = toOdooAssetUrl('https://cdn.example.com/part.png', 'http://lc.rm.com');
  assert.equal(url, 'http://lc.rm.com/lab/api/asset?url=' + encodeURIComponent('https://cdn.example.com/part.png'));
});

test('same-origin Odoo asset paths are kept, other same-origin paths are rejected', () => {
  assert.equal(
    toOdooAssetUrl('/lab/api/asset?url=x', 'http://lc.rm.com'),
    'http://lc.rm.com/lab/api/asset?url=x',
  );
  assert.equal(toOdooAssetUrl('/web/image/1', 'http://lc.rm.com'), 'http://lc.rm.com/web/image/1');
  assert.equal(toOdooAssetUrl('/other/path', 'http://lc.rm.com'), null);
  assert.equal(toOdooAssetUrl('javascript:alert(1)', 'http://lc.rm.com'), null);
  assert.equal(toOdooAssetUrl('', 'http://lc.rm.com'), null);
});

test('bytesToBase64 encodes binary data', () => {
  assert.equal(bytesToBase64(new Uint8Array([104, 105])), 'aGk=');
  assert.equal(bytesToBase64(new Uint8Array([])), '');
});

test('relay image loader wraps the Odoo asset URL and sends the pairing token', async () => {
  let captured;
  const loader = createImageLoader({
    serverUrl: 'http://lc.rm.com',
    mode: 'relay',
    relayUrl: 'http://127.0.0.1:49621',
    pairingToken: 'pair-token-123456',
    transport: {
      async requestBinary(input) {
        captured = input;
        return { buffer: new Uint8Array([1, 2, 3]).buffer, contentType: 'image/png', status: 200 };
      },
    },
  });
  const first = await loader.load('https://cdn.example.com/part.png');
  assert.equal(first.supported, true);
  assert.equal(first.dataUrl, 'data:image/png;base64,AQID');
  assert.ok(captured.url.startsWith('http://127.0.0.1:49621/asset?url='));
  assert.equal(captured.headers.Authorization, 'Bearer pair-token-123456');
  const decoded = decodeURIComponent(captured.url.split('url=')[1]);
  assert.equal(decoded, 'http://lc.rm.com/lab/api/asset?url=' + encodeURIComponent('https://cdn.example.com/part.png'));
});

test('image loader caches identical assets', async () => {
  let calls = 0;
  const loader = createImageLoader({
    serverUrl: 'http://lc.rm.com',
    mode: 'relay',
    relayUrl: 'http://127.0.0.1:49621',
    pairingToken: 'pair-token-123456',
    transport: {
      async requestBinary() {
        calls += 1;
        return { buffer: new Uint8Array([1]).buffer, contentType: 'image/png', status: 200 };
      },
    },
  });
  await loader.load('https://cdn.example.com/part.png');
  await loader.load('https://cdn.example.com/part.png');
  assert.equal(calls, 1);
});
