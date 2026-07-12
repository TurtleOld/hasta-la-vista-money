import assert from 'node:assert/strict';
import test from 'node:test';

import {
  calculateCenteredScanRegion,
  isFNSReceiptQR,
  shouldScanFullFrame,
} from '../../static/js/receipt-qr-core.mjs';

test('calculateCenteredScanRegion returns a centered square', () => {
  assert.deepEqual(calculateCenteredScanRegion(1920, 1080), {
    x: 571,
    y: 151,
    width: 777,
    height: 777,
  });
});

test('isFNSReceiptQR accepts a complete FNS payload', () => {
  assert.equal(
    isFNSReceiptQR('t=20260712T1200&s=123.45&fn=1&i=2&fp=3&n=1'),
    true,
  );
});

test('isFNSReceiptQR rejects an unrelated or incomplete QR payload', () => {
  assert.equal(isFNSReceiptQR('https://example.com'), false);
  assert.equal(isFNSReceiptQR('t=20260712T1200&s=123.45'), false);
  assert.equal(isFNSReceiptQR(''), false);
});

test('shouldScanFullFrame observes the configured interval', () => {
  assert.equal(shouldScanFullFrame(999, 0, 1000), false);
  assert.equal(shouldScanFullFrame(1000, 0, 1000), true);
});
