import assert from 'node:assert/strict';
import test from 'node:test';

import {
  autozoomStep,
  calculateCenteredScanRegion,
  createAutozoomState,
  isFNSReceiptQR,
  createScanHints,
  frameMetrics,
  isPhotoUploadAccepted,
  magnificationRegion,
  measureQR,
  PHOTO_MAGNIFICATION,
  createPhotoButton,
  parseQRVersion,
  photoButton,
  pickCamera,
  rankCameras,
  scanHints,
  scanFrames,
  shouldScanFullFrame,
  zoomCorridor,
  zoomLimit,
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

const ZOOM_CAPS = { zoom: { min: 1, max: 8, step: 0.1 } };
const ZOOM_FRAME = { width: 1920, height: 1080 };

function small() {
  return { pxPerModule: 2.9, share: 0.1, center: { x: 1, y: 1 } };
}

function large() {
  return { pxPerModule: 20, share: 0.71, center: { x: 1, y: 1 } };
}

function fine() {
  return { pxPerModule: 3, share: 0.7, center: { x: 1, y: 1 } };
}

test('zoomCorridor intersects [1.5; 3] with the camera range', () => {
  assert.deepEqual(zoomCorridor(ZOOM_CAPS), {
    min: 1.5,
    max: 3,
    step: 0.1,
    base: 1,
  });
  const narrow = zoomCorridor({ zoom: { min: 1, max: 2.55, step: 0.5 } });
  assert.equal(narrow.min, 1.5);
  assert.equal(narrow.max, 2.5);
  assert.equal(zoomCorridor({ zoom: { min: 2, max: 8, step: 0.1 } }).min, 2);
});

test('zoomCorridor is null without usable zoom', () => {
  assert.equal(zoomCorridor(null), null);
  assert.equal(zoomCorridor({}), null);
  assert.equal(zoomCorridor({ zoom: { min: 1, max: 1, step: 0.1 } }), null);
  assert.equal(zoomCorridor({ zoom: { min: 3, max: 2, step: 0.1 } }), null);
  assert.equal(zoomCorridor({ zoom: { min: 4, max: 8, step: 0.1 } }), null);
});

test('measureQR returns px per module, share and center', () => {
  const measurement = measureQR(
    { position: squarePosition(100, 200, 210), version: 1 },
    ZOOM_FRAME,
  );
  assert.equal(measurement.pxPerModule, 10);
  assert.equal(measurement.share, 210 / 1080);
  assert.deepEqual(measurement.center, { x: 205, y: 305 });
});

test('measureQR has no px per module without Version', () => {
  const measurement = measureQR(
    { position: squarePosition(0, 0, 100), version: null },
    ZOOM_FRAME,
  );
  assert.equal(measurement.pxPerModule, null);
});

test('createAutozoomState starts at 2x clamped into the corridor', () => {
  assert.equal(createAutozoomState(ZOOM_CAPS).zoom, 2);
  const high = createAutozoomState({ zoom: { min: 2.5, max: 8, step: 0.1 } });
  assert.equal(high.zoom, 2.5);
  assert.equal(createAutozoomState({}).zoom, null);
});

test('autozoomStep returns null without zoom', () => {
  const state = createAutozoomState({});
  for (let i = 0; i < 5; i += 1) {
    assert.equal(autozoomStep(state, small(), i * 1000).zoom, null);
  }
});

test('autozoomStep zooms in x1.25 after 3 consistent small measurements', () => {
  let state = createAutozoomState(ZOOM_CAPS);
  let step = autozoomStep(state, small(), 0);
  assert.equal(step.zoom, null);
  step = autozoomStep(step.state, small(), 100);
  assert.equal(step.zoom, null);
  step = autozoomStep(step.state, small(), 200);
  assert.equal(step.zoom, 2.5);
  assert.equal(step.state.zoom, 2.5);
});

test('autozoomStep zooms out /1.25 on large share', () => {
  let step = { state: createAutozoomState(ZOOM_CAPS) };
  for (let i = 0; i < 3; i += 1) {
    step = autozoomStep(step.state, large(), i * 100);
  }
  assert.equal(step.zoom, 1.6);
});

test('autozoomStep thresholds: boundary values do not trigger', () => {
  let step = { state: createAutozoomState(ZOOM_CAPS) };
  for (let i = 0; i < 6; i += 1) {
    step = autozoomStep(step.state, fine(), i * 1000);
    assert.equal(step.zoom, null);
  }
});

test('autozoomStep without Version zooms in only below share 0.25', () => {
  const measure = (share) => ({
    pxPerModule: null,
    share,
    center: { x: 0, y: 0 },
  });
  const run = (share) => {
    let step = { state: createAutozoomState(ZOOM_CAPS) };
    for (let i = 0; i < 3; i += 1) {
      step = autozoomStep(step.state, measure(share), i * 100);
    }
    return step.zoom;
  };
  assert.equal(run(0.24), 2.5);
  assert.equal(run(0.25), null);
  assert.equal(run(0.26), null);
});

test('autozoomStep needs the same condition 3 times in a row', () => {
  let step = autozoomStep(createAutozoomState(ZOOM_CAPS), small(), 0);
  step = autozoomStep(step.state, small(), 100);
  step = autozoomStep(step.state, fine(), 200);
  step = autozoomStep(step.state, small(), 300);
  step = autozoomStep(step.state, small(), 400);
  assert.equal(step.zoom, null);
  step = autozoomStep(step.state, small(), 500);
  assert.equal(step.zoom, 2.5);
});

test('autozoomStep does not change zoom when QR is not found', () => {
  let step = autozoomStep(createAutozoomState(ZOOM_CAPS), small(), 0);
  step = autozoomStep(step.state, small(), 100);
  step = autozoomStep(step.state, null, 200);
  step = autozoomStep(step.state, small(), 300);
  assert.equal(step.zoom, null);
  assert.equal(step.state.zoom, 2);
});

test('autozoomStep ignores measurements for 300 ms and waits 600 ms', () => {
  let step = { state: createAutozoomState(ZOOM_CAPS) };
  for (let i = 0; i < 3; i += 1) {
    step = autozoomStep(step.state, small(), i * 100);
  }
  assert.equal(step.state.changedAt, 200);
  // within 300 ms of the change: ignored, streak does not grow
  step = autozoomStep(step.state, small(), 300);
  step = autozoomStep(step.state, small(), 499);
  assert.equal(step.state.streak, 0);
  // after 300 ms they count, but the next change waits until 600 ms
  step = autozoomStep(step.state, small(), 500);
  step = autozoomStep(step.state, small(), 600);
  step = autozoomStep(step.state, small(), 799);
  assert.equal(step.zoom, null);
  step = autozoomStep(step.state, small(), 800);
  assert.equal(step.zoom, 3);
});

test('autozoomStep clamps to the corridor and does not jitter at the edge', () => {
  let step = { state: createAutozoomState(ZOOM_CAPS) };
  let now = 0;
  const zooms = [];
  for (let i = 0; i < 30; i += 1) {
    step = autozoomStep(step.state, small(), now);
    now += 400;
    if (step.zoom !== null) {
      zooms.push(step.zoom);
    }
  }
  assert.deepEqual(zooms, [2.5, 3]);
  assert.equal(zoomLimit(step.state), 'max');
});

test('autozoomStep rounds to the camera step', () => {
  const caps = { zoom: { min: 1, max: 8, step: 0.5 } };
  let step = { state: createAutozoomState(caps) };
  for (let i = 0; i < 3; i += 1) {
    step = autozoomStep(step.state, small(), i * 100);
  }
  // 2 * 1.25 = 2.5 is on the grid; 2.5 / 1.25 = 2, then 1.6 -> 1.5
  assert.equal(step.zoom, 2.5);
  for (let i = 0; i < 3; i += 1) {
    step = autozoomStep(step.state, large(), 1000 + i * 100);
  }
  assert.equal(step.zoom, 2);
  for (let i = 0; i < 3; i += 1) {
    step = autozoomStep(step.state, large(), 2000 + i * 100);
  }
  assert.equal(step.zoom, 1.5);
});

test('zoomLimit reports the corridor edges and missing zoom', () => {
  assert.equal(zoomLimit(createAutozoomState({})), 'unavailable');
  assert.equal(zoomLimit(createAutozoomState(ZOOM_CAPS)), null);
  const low = createAutozoomState({ zoom: { min: 2, max: 8, step: 0.1 } });
  assert.equal(zoomLimit(low), 'min');
});

const HINT_BASE = {
  brightness: 140,
  sharpness: 100,
  qr: null,
  wrongQr: false,
  zoomStepped: false,
  zoom: { available: false },
  torch: { available: false, on: false },
};

function runHints(steps, { start = 0, stepMs = 100 } = {}) {
  let state = createScanHints(start);
  let result = null;
  for (const [index, observation] of steps.entries()) {
    result = scanHints(
      state,
      { ...HINT_BASE, ...observation },
      start + index * stepMs,
    );
    state = result.state;
  }
  return result;
}

function repeat(observation, count) {
  return Array.from({ length: count }, () => observation);
}

// A scenario that starts at t=0 and holds one observation for `ms`,
// sampled every 100 ms; returns the hint at the end.
function holdHint(observation, ms) {
  return runHints(repeat(observation, ms / 100 + 1)).hint;
}

test('hints: default is shown during warmup even with a dark frame', () => {
  assert.equal(holdHint({ brightness: 10 }, 700).id, 'idle');
});

test('hints: a condition becomes a candidate only after 400 ms', () => {
  // Warmup ends at 800 ms; the dark condition starts counting from t=0.
  assert.equal(holdHint({ brightness: 10 }, 800).id, 'dark');
  const steps = [...repeat({}, 8), ...repeat({ brightness: 10 }, 4)];
  // Dark begins at t=800 (index 8); at t=1100 it has held 300 ms.
  assert.equal(runHints(steps).hint.id, 'idle');
  // At t=1200 it has held 400 ms.
  assert.equal(runHints([...steps, { brightness: 10 }]).hint.id, 'dark');
});

test('hints: dark enters below 40 and leaves above 55', () => {
  const dark = (brightness) =>
    runHints([...repeat({ brightness: 10 }, 10), ...repeat({ brightness }, 20)])
      .hint.id;
  assert.equal(holdHint({ brightness: 40 }, 1000).id, 'idle');
  assert.equal(holdHint({ brightness: 39 }, 1000).id, 'dark');
  assert.equal(dark(55), 'dark');
  assert.equal(dark(56), 'idle');
});

test('hints: dark text depends on the torch', () => {
  const torchOff = { available: true, on: false };
  const torchOn = { available: true, on: true };
  assert.equal(
    holdHint({ brightness: 10, torch: torchOff }, 1000).key,
    'darkTorch',
  );
  assert.equal(holdHint({ brightness: 10, torch: torchOn }, 1000).key, 'dark');
  assert.equal(holdHint({ brightness: 10 }, 1000).key, 'dark');
});

test('hints: torch toggle changes the text without delay', () => {
  const dark = { brightness: 10 };
  const result = runHints([
    ...repeat({ ...dark, torch: { available: true, on: false } }, 12),
    { ...dark, torch: { available: true, on: true } },
  ]);
  assert.equal(result.hint.id, 'dark');
  assert.equal(result.hint.key, 'dark');
});

test('hints: blur below 35% of the 3 s peak, leaves above 50%', () => {
  const blur = (value, tail = 20) =>
    runHints([
      ...repeat({ sharpness: 100 }, 5),
      ...repeat({ sharpness: value }, tail),
    ]).hint.id;
  assert.equal(blur(35), 'idle');
  assert.equal(blur(34), 'blurry');
  const recover = (value) =>
    runHints([
      ...repeat({ sharpness: 100 }, 5),
      ...repeat({ sharpness: 10 }, 10),
      ...repeat({ sharpness: value }, 12),
    ]).hint.id;
  assert.equal(recover(50), 'blurry');
  assert.equal(recover(51), 'idle');
});

test('hints: the sharpness peak is forgotten after 3 s', () => {
  const steps = [{ sharpness: 100 }, ...repeat({ sharpness: 30 }, 40)];
  assert.equal(runHints(steps).hint.id, 'idle');
});

test('hints: too small needs px/module below 3 and exhausted zoom', () => {
  const qr = (pxPerModule) => ({ pxPerModule, share: 0.4 });
  assert.equal(holdHint({ qr: qr(3) }, 1000).id, 'found');
  assert.equal(holdHint({ qr: qr(2.99) }, 1000).id, 'tooSmall');
  const zoom = (atMax) => ({ available: true, atMin: false, atMax });
  assert.equal(holdHint({ qr: qr(2), zoom: zoom(false) }, 1000).id, 'found');
  assert.equal(holdHint({ qr: qr(2), zoom: zoom(true) }, 1000).id, 'tooSmall');
});

test('hints: without Version small means share below 0.25', () => {
  const qr = (share) => ({ pxPerModule: null, share });
  assert.equal(holdHint({ qr: qr(0.25) }, 1000).id, 'found');
  assert.equal(holdHint({ qr: qr(0.24) }, 1000).id, 'tooSmall');
});

test('hints: too large needs share above 0.7 and exhausted zoom', () => {
  const qr = (share) => ({ pxPerModule: 10, share });
  assert.equal(holdHint({ qr: qr(0.7) }, 1000).id, 'found');
  assert.equal(holdHint({ qr: qr(0.71) }, 1000).id, 'tooLarge');
  const zoom = (atMin) => ({ available: true, atMin, atMax: false });
  assert.equal(holdHint({ qr: qr(0.9), zoom: zoom(false) }, 1000).id, 'found');
  assert.equal(
    holdHint({ qr: qr(0.9), zoom: zoom(true) }, 1000).id,
    'tooLarge',
  );
});

test('hints: found is shown for a detection without text', () => {
  assert.equal(
    holdHint({ qr: { pxPerModule: 8, share: 0.4 } }, 1000).id,
    'found',
  );
});

test('hints: not found appears after 4 s without a QR', () => {
  assert.equal(holdHint({}, 3900).id, 'idle');
  assert.equal(holdHint({}, 4000).id, 'notFound');
});

test('hints: not found waits 4 s since the last detection', () => {
  const qr = { pxPerModule: 8, share: 0.4 };
  const lost = (ms) =>
    runHints([...repeat({ qr }, 10), ...repeat({}, ms / 100)]).hint.id;
  // The last detection is at t=900.
  assert.equal(lost(3900), 'idle');
  assert.equal(lost(4000), 'notFound');
});

test('hints: priority order picks the first active condition', () => {
  const qr = { pxPerModule: 1, share: 0.9 };
  const all = {
    brightness: 10,
    sharpness: 100,
    qr,
    zoom: { available: false },
  };
  const blurSteps = [
    { sharpness: 100 },
    ...repeat({ ...all, sharpness: 1 }, 20),
  ];
  assert.equal(runHints(blurSteps).hint.id, 'dark');
  assert.equal(
    runHints([
      { sharpness: 100 },
      ...repeat({ ...all, brightness: 140, sharpness: 1 }, 20),
    ]).hint.id,
    'blurry',
  );
  assert.equal(
    runHints(repeat({ ...all, brightness: 140 }, 20)).hint.id,
    'tooSmall',
  );
  assert.equal(
    runHints(
      repeat(
        { ...all, brightness: 140, qr: { pxPerModule: 10, share: 0.9 } },
        20,
      ),
    ).hint.id,
    'tooLarge',
  );
  assert.equal(
    runHints(
      repeat(
        { ...all, brightness: 140, qr: { pxPerModule: 10, share: 0.4 } },
        20,
      ),
    ).hint.id,
    'found',
  );
});

test('hints: wrong QR wins immediately, even during warmup', () => {
  const result = runHints([{ brightness: 10 }, { wrongQr: true }]);
  assert.equal(result.hint.id, 'wrongQr');
});

test('hints: wrong QR stays 3 s after the last read', () => {
  const read = [{ wrongQr: true }];
  const after = (ms) => runHints([...read, ...repeat({}, ms / 100)]).hint.id;
  assert.equal(after(2900), 'wrongQr');
  assert.equal(after(3000), 'idle');
});

test('hints: wrong QR over a shown hint ignores the minimum dwell', () => {
  const steps = [
    ...repeat({ brightness: 10 }, 12),
    { brightness: 10, wrongQr: true },
  ];
  assert.equal(runHints(steps).hint.id, 'wrongQr');
});

test('hints: a shown hint stays at least 1.5 s', () => {
  // Dark is shown from t=800 and the light comes back right away.
  const steps = (length) => [
    ...repeat({ brightness: 10 }, 9),
    ...repeat({ brightness: 140 }, length - 9),
  ];
  // Last frame at t=2200: only 1400 ms have passed.
  assert.equal(runHints(steps(23)).hint.id, 'dark');
  // Last frame at t=2300: exactly 1500 ms.
  assert.equal(runHints(steps(24)).hint.id, 'idle');
});

test('hints: measurements are frozen for 300 ms after a zoom step', () => {
  const dark = { brightness: 10 };
  const bright = { brightness: 140 };
  const beforeStep = repeat(dark, 12);
  // Frozen frames keep the previous state even though the frame is bright.
  const frozen = runHints([
    ...beforeStep,
    { ...bright, zoomStepped: true },
    ...repeat(bright, 2),
  ]);
  assert.equal(frozen.state.active.dark, true);
  // The step at index 12 (t=1200) freezes until t=1500 (exclusive).
  const thawed = runHints([
    ...beforeStep,
    { ...bright, zoomStepped: true },
    ...repeat(bright, 3),
  ]);
  assert.equal(thawed.state.active.dark, false);
});

test('hints: frozen sharpness does not enter the peak window', () => {
  const frozen = runHints([
    { sharpness: 100 },
    { sharpness: 5, zoomStepped: true },
    { sharpness: 5 },
  ]);
  assert.equal(frozen.state.samples.length, 1);
});

function solidImage(width, height, value) {
  return {
    width,
    height,
    data: new Uint8ClampedArray(width * height * 4).fill(value),
  };
}

test('frameMetrics: a flat image has its brightness and no sharpness', () => {
  const metrics = frameMetrics(solidImage(64, 64, 100));
  assert.ok(Math.abs(metrics.brightness - 100) < 1e-9);
  assert.equal(metrics.sharpness, 0);
});

test('frameMetrics: a checkerboard is sharper than a flat image', () => {
  const image = solidImage(64, 64, 0);
  for (let y = 0; y < 64; y += 1) {
    for (let x = 0; x < 64; x += 1) {
      if (((x >> 2) + (y >> 2)) % 2 === 0) {
        image.data.fill(255, (y * 64 + x) * 4, (y * 64 + x) * 4 + 3);
      }
    }
  }
  assert.ok(frameMetrics(image).sharpness > 1000);
});

test('frameMetrics: an image smaller than the grid is safe', () => {
  assert.deepEqual(frameMetrics(solidImage(4, 4, 10)), {
    brightness: 0,
    sharpness: 0,
  });
});

test('hints: a foreign QR read restarts the 4 s not-found timer', () => {
  // The read is at t=2000; not-found may appear only from t=6000 (6500 after the idle dwell).
  const at = (ms) =>
    runHints([...repeat({}, 20), { wrongQr: true }, ...repeat({}, ms / 100)])
      .hint.id;
  assert.equal(at(4400), 'idle');
  assert.equal(at(4500), 'notFound');
});

test('photoButton appears exactly 5 s after the camera opened', () => {
  const state = createPhotoButton(1000);
  const before = photoButton(state, 5999);
  assert.equal(before.visible, false);
  const at = photoButton(before.state, 6000);
  assert.equal(at.visible, true);
});

test('photoButton stays visible once shown', () => {
  let result = photoButton(createPhotoButton(0), 5000);
  result = photoButton(result.state, 60000);
  assert.equal(result.visible, true);
});

test('photo magnification keeps the source resolution of the crop', () => {
  // 222 px QR -> 6 px/module, crop with padding stays below 1200 px.
  const region = magnificationRegion(
    squarePosition(1000, 1000, 222),
    5,
    { width: 4000, height: 3000 },
    PHOTO_MAGNIFICATION,
  );
  assert.equal(region.scale, 1);
});

test('photo magnification never upscales a small QR', () => {
  const region = magnificationRegion(
    squarePosition(1000, 1000, 74),
    5,
    { width: 4000, height: 3000 },
    PHOTO_MAGNIFICATION,
  );
  assert.equal(region.scale, 1);
});

test('photo magnification shrinks a crop over 1200 px', () => {
  const region = magnificationRegion(
    squarePosition(500, 500, 1400),
    5,
    { width: 4000, height: 3000 },
    PHOTO_MAGNIFICATION,
  );
  const longest = Math.max(region.width, region.height);
  assert.ok(Math.abs(longest * region.scale - 1200) < 1e-6);
});

test('photo magnification floors the shrink at minPxPerModule', () => {
  assert.equal(PHOTO_MAGNIFICATION.minPxPerModule, 3);
  // 1400 px QR -> 37.8 px/module; the 1200 px cap would give ~25 px/module.
  const region = magnificationRegion(
    squarePosition(500, 500, 1400),
    5,
    { width: 4000, height: 3000 },
    { ...PHOTO_MAGNIFICATION, minPxPerModule: 30 },
  );
  assert.ok(Math.abs(region.scale * (1400 / 37) - 30) < 1e-6);
});

test('scanFrames passes region options to the magnification', async () => {
  const frames = [{ image: { width: 4000, height: 3000 }, x: 0, y: 0 }];
  const regions = [];
  let calls = 0;
  await scanFrames({
    frames,
    frameSize: { width: 4000, height: 3000 },
    regionOptions: PHOTO_MAGNIFICATION,
    decode: async () => {
      calls += 1;
      return calls === 1
        ? [{ text: '', position: squarePosition(1000, 1000, 74), version: 5 }]
        : [{ text: 'ok' }];
    },
    magnify: async (image, region) => {
      regions.push(region);
      return image;
    },
  });
  assert.equal(regions[0].scale, 1);
});

test('photo upload is accepted only after a successful redirect', () => {
  assert.equal(isPhotoUploadAccepted({ ok: true, redirected: true }), true);
  assert.equal(isPhotoUploadAccepted({ ok: true, redirected: false }), false);
  assert.equal(isPhotoUploadAccepted({ ok: false, redirected: true }), false);
});
