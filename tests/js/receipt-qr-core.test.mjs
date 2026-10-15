import assert from 'node:assert/strict';
import test from 'node:test';

import {
  calculateCenteredScanRegion,
  isFNSReceiptQR,
  magnificationRegion,
  parseQRVersion,
  pickCamera,
  rankCameras,
  scanFrames,
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

function camera(id, label, capabilities) {
  return { deviceId: id, label, capabilities };
}

function caps(overrides = {}) {
  return {
    facingMode: ['environment'],
    focusMode: [],
    torch: false,
    zoom: { min: 1, max: 1 },
    imageWidth: { max: 1000 },
    ...overrides,
  };
}

test('rankCameras prefers continuous focus over torch', () => {
  const ranked = rankCameras([
    camera('torch', 'camera2 1, facing back', caps({ torch: true })),
    camera(
      'focus',
      'camera2 2, facing back',
      caps({ focusMode: ['continuous'] }),
    ),
  ]);
  assert.deepEqual(
    ranked.map((item) => item.deviceId),
    ['focus', 'torch'],
  );
});

test('rankCameras prefers torch over zoom.max', () => {
  const ranked = rankCameras([
    camera(
      'zoom',
      'camera2 1, facing back',
      caps({ zoom: { min: 1, max: 8 } }),
    ),
    camera('torch', 'camera2 2, facing back', caps({ torch: true })),
  ]);
  assert.equal(ranked[0].deviceId, 'torch');
});

test('rankCameras prefers larger zoom.max, then imageWidth.max', () => {
  const zoom = (max, width) =>
    caps({ zoom: { min: 1, max }, imageWidth: { max: width } });
  assert.equal(
    rankCameras([
      camera('a', 'camera2 0, facing back', zoom(4, 9000)),
      camera('b', 'camera2 2, facing back', zoom(5, 100)),
    ])[0].deviceId,
    'b',
  );
  assert.equal(
    rankCameras([
      camera('a', 'camera2 0, facing back', zoom(4, 100)),
      camera('b', 'camera2 2, facing back', zoom(4, 200)),
    ])[0].deviceId,
    'b',
  );
});

test('rankCameras falls back to the smaller camera index', () => {
  const ranked = rankCameras([
    camera('two', 'camera2 2, facing back', caps()),
    camera('zero', 'camera2 0, facing back', caps()),
  ]);
  assert.equal(ranked[0].deviceId, 'zero');
});

test('rankCameras excludes front cameras', () => {
  const ranked = rankCameras([
    camera(
      'front',
      'camera2 1, facing front',
      caps({ facingMode: ['user'], focusMode: ['continuous'], torch: true }),
    ),
    camera('front-label', 'camera2 3, facing front', undefined),
    camera('back', 'camera2 0, facing back', caps()),
  ]);
  assert.deepEqual(
    ranked.map((item) => item.deviceId),
    ['back'],
  );
});

test('pickCamera returns the saved deviceId when it is listed', () => {
  const cameras = [
    camera('best', 'camera2 0, facing back', caps({ torch: true })),
    camera('saved', 'camera2 2, facing back', caps()),
  ];
  assert.equal(pickCamera(cameras, 'saved'), 'saved');
  assert.equal(pickCamera(cameras, 'gone'), 'best');
  assert.equal(pickCamera(cameras, null), 'best');
});

test('pickCamera ignores a saved front camera', () => {
  const cameras = [
    camera('front', 'camera2 1, facing front', caps({ facingMode: ['user'] })),
    camera('back', 'camera2 0, facing back', caps()),
  ];
  assert.equal(pickCamera(cameras, 'front'), 'back');
});

test('pickCamera takes the first back camera without capabilities', () => {
  const cameras = [
    camera('front', 'camera2 1, facing front'),
    camera('first', 'camera2 2, facing back'),
    camera('second', 'camera2 0, facing back'),
  ];
  assert.equal(pickCamera(cameras, null), 'first');
});

test('pickCamera returns null when no back camera is found', () => {
  assert.equal(pickCamera([], null), null);
  assert.equal(pickCamera([camera('x', '')], null), null);
});

function squarePosition(x, y, side) {
  return {
    topLeft: { x, y },
    topRight: { x: x + side, y },
    bottomRight: { x: x + side, y: y + side },
    bottomLeft: { x, y: y + side },
  };
}

const FRAME = { width: 1920, height: 1080 };

// Version 5 -> 37 modules.
test('magnificationRegion scales a small QR to 6 px per module', () => {
  // side 74 -> 2 px/module -> scale 3
  const region = magnificationRegion(squarePosition(500, 500, 74), 5, FRAME);
  assert.equal(region.scale, 3);
});

test('magnificationRegion clamps the scale to [1; 4]', () => {
  // 1.5 px/module would need 4, 1 px/module needs 6 -> clamped to 4
  assert.equal(
    magnificationRegion(squarePosition(500, 500, 37), 5, FRAME).scale,
    4,
  );
  assert.equal(
    magnificationRegion(squarePosition(500, 500, 55.5), 5, FRAME).scale,
    4,
  );
  // 6 px/module -> 1; 12 px/module would need 0.5 -> clamped to 1
  assert.equal(
    magnificationRegion(squarePosition(500, 500, 222), 5, FRAME).scale,
    1,
  );
  assert.equal(
    magnificationRegion(squarePosition(300, 300, 444), 5, FRAME).scale,
    1,
  );
  // just inside the range: 2 px/module -> 3
  assert.equal(
    magnificationRegion(squarePosition(500, 500, 74), 5, FRAME).scale,
    3,
  );
});

test('magnificationRegion uses 4 modules of padding for small codes', () => {
  // side 74, module 2 px: 4 modules = 8 px, 15 % = 11.1 px -> 15 % wins
  // side 37, module 1 px: 4 modules = 4 px, 15 % = 5.55 -> 15 % wins
  // side 370, module 10 px: 4 modules = 40 px, 15 % = 55.5 -> 15 % wins
  // 4 modules win only if 4/37 * side... 4 modules = 10.8 % of side < 15 %
  const region = magnificationRegion(squarePosition(500, 500, 74), 5, FRAME);
  assert.equal(region.x, 500 - 12);
  assert.equal(region.width, 74 + 24);
});

test('magnificationRegion padding takes 4 modules when version is large', () => {
  // Version 40 -> 177 modules, side 177 -> 1 px/module, 4 modules = 4 px,
  // 15 % = 26.55 px -> 15 % wins. With Version 1 (21 modules), side 21:
  // 4 modules = 4 px, 15 % = 3.15 px -> 4 modules win.
  const region = magnificationRegion(squarePosition(500, 500, 21), 1, FRAME);
  assert.equal(region.x, 496);
  assert.equal(region.width, 29);
});

test('magnificationRegion clips the region to the frame', () => {
  const region = magnificationRegion(squarePosition(2, 3, 74), 5, FRAME);
  assert.equal(region.x, 0);
  assert.equal(region.y, 0);
  assert.equal(region.width, 2 + 74 + 12);
  const right = magnificationRegion(squarePosition(1850, 1000, 70), 5, FRAME);
  assert.equal(right.x + right.width, 1920);
  assert.equal(right.y + right.height, 1080);
});

test('magnificationRegion defaults to Version 5', () => {
  const unknown = magnificationRegion(
    squarePosition(500, 500, 74),
    null,
    FRAME,
  );
  const five = magnificationRegion(squarePosition(500, 500, 74), 5, FRAME);
  assert.deepEqual(unknown, five);
  assert.deepEqual(
    magnificationRegion(squarePosition(500, 500, 74), undefined, FRAME),
    five,
  );
});

test('magnificationRegion keeps the sides within the limit', () => {
  // Version 5, side 37 -> 1 px/module -> scale 4, region 37 px -> 148 px
  const options = { paddingRatio: 0, minPaddingModules: 0 };
  const position = squarePosition(500, 500, 37);
  const at = magnificationRegion(position, 5, FRAME, {
    ...options,
    maxSide: 148,
  });
  assert.equal(at.scale, 4);
  const above = magnificationRegion(position, 5, FRAME, {
    ...options,
    maxSide: 147,
  });
  assert.equal(above.scale, 147 / 37);
  const below = magnificationRegion(position, 5, FRAME, {
    ...options,
    maxSide: 149,
  });
  assert.equal(below.scale, 4);
});

test('magnificationRegion uses a 1200 px limit by default', () => {
  // Version 40, side 250 -> 1.41 px/module -> scale 4; region 326 px
  // (15 % padding) would be 1300 px -> reduced to 1200 / 326
  const region = magnificationRegion(squarePosition(500, 400, 250), 40, FRAME);
  assert.equal(region.width, 326);
  assert.equal(region.scale, 1200 / 326);
});

test('parseQRVersion reads Version from the extra JSON', () => {
  assert.equal(parseQRVersion('{"Version":"7","ECLevel":"M"}'), 7);
  assert.equal(parseQRVersion('{"Version":9}'), 9);
  assert.equal(parseQRVersion(''), null);
  assert.equal(parseQRVersion('not json'), null);
  assert.equal(parseQRVersion('{"Version":"0"}'), null);
  assert.equal(parseQRVersion(undefined), null);
});

function fakeImage(name, width = 100, height = 100) {
  return { name, width, height };
}

function pipelineHarness(script) {
  const calls = [];
  const decode = async (image) => {
    calls.push(`decode:${image.name}`);
    return script[image.name] ?? [];
  };
  const magnify = async (image, region) => {
    calls.push(`magnify:${image.name}`);
    return fakeImage(`${image.name}+zoom`, region.width, region.height);
  };
  return { calls, decode, magnify };
}

const unread = (x, y, size) => ({
  text: '',
  position: squarePosition(x, y, size),
  version: 5,
});

test('scanFrames stops at the first successful pass', async () => {
  const { calls, decode, magnify } = pipelineHarness({
    center: [{ text: 'ok', position: squarePosition(0, 0, 10), version: 5 }],
  });
  const result = await scanFrames({
    frames: [
      { image: fakeImage('center'), x: 10, y: 10 },
      { image: fakeImage('full', 200, 200), x: 0, y: 0 },
    ],
    frameSize: { width: 200, height: 200 },
    decode,
    magnify,
  });
  assert.equal(result.value, 'ok');
  assert.equal(result.magnified, false);
  assert.deepEqual(calls, ['decode:center']);
});

test('scanFrames magnifies the center, then scans the full frame, then magnifies it', async () => {
  const { calls, decode, magnify } = pipelineHarness({
    center: [unread(10, 10, 20)],
    full: [unread(50, 50, 20)],
  });
  const result = await scanFrames({
    frames: [
      { image: fakeImage('center'), x: 10, y: 10 },
      { image: fakeImage('full', 200, 200), x: 0, y: 0 },
    ],
    frameSize: { width: 200, height: 200 },
    decode,
    magnify,
  });
  assert.deepEqual(calls, [
    'decode:center',
    'magnify:center',
    'decode:center+zoom',
    'decode:full',
  ]);
  assert.equal(result.value, '');
  assert.equal(result.magnified, true);
});

test('scanFrames magnifies the full frame when the center has no detection', async () => {
  const { calls, decode, magnify } = pipelineHarness({
    full: [unread(50, 50, 20)],
  });
  const result = await scanFrames({
    frames: [
      { image: fakeImage('center'), x: 10, y: 10 },
      { image: fakeImage('full', 200, 200), x: 0, y: 0 },
    ],
    frameSize: { width: 200, height: 200 },
    decode,
    magnify,
  });
  assert.deepEqual(calls, [
    'decode:center',
    'decode:full',
    'magnify:full',
    'decode:full+zoom',
  ]);
  assert.equal(result.magnified, true);
});

test('scanFrames reads the magnified region', async () => {
  const { decode, magnify } = pipelineHarness({
    center: [unread(10, 10, 20)],
    'center+zoom': [
      { text: 'zoomed', position: squarePosition(0, 0, 5), version: 5 },
    ],
  });
  const result = await scanFrames({
    frames: [{ image: fakeImage('center'), x: 0, y: 0 }],
    frameSize: { width: 100, height: 100 },
    decode,
    magnify,
  });
  assert.equal(result.value, 'zoomed');
  assert.equal(result.magnified, true);
  assert.equal(result.detection, null);
});

test('scanFrames reports the detection closest to the center in full-frame coordinates', async () => {
  const { decode, magnify } = pipelineHarness({
    center: [unread(0, 0, 10), unread(35, 35, 10)],
  });
  const result = await scanFrames({
    frames: [{ image: fakeImage('center'), x: 100, y: 50 }],
    frameSize: { width: 400, height: 300 },
    decode,
    magnify,
  });
  assert.equal(result.value, '');
  assert.equal(result.detection.version, 5);
  assert.deepEqual(result.detection.position.topLeft, { x: 135, y: 85 });
});

test('scanFrames returns an empty result when nothing is found', async () => {
  const { calls, decode, magnify } = pipelineHarness({});
  const result = await scanFrames({
    frames: [{ image: fakeImage('center'), x: 0, y: 0 }],
    frameSize: { width: 100, height: 100 },
    decode,
    magnify,
  });
  assert.deepEqual(result, { value: '', detection: null, magnified: false });
  assert.deepEqual(calls, ['decode:center']);
});
