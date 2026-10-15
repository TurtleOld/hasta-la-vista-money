const REQUIRED_FNS_FIELDS = ['t', 's', 'fn', 'i', 'fp', 'n'];

const TARGET_PX_PER_MODULE = 6;
const MIN_MAGNIFICATION_SCALE = 1;
const MAX_MAGNIFICATION_SCALE = 4;
const MAX_MAGNIFIED_SIDE = 1200;
const DEFAULT_QR_VERSION = 5;
const MIN_PADDING_MODULES = 4;
const PADDING_RATIO = 0.15;
const AUTOZOOM_MIN = 1.5;
const AUTOZOOM_MAX = 3;
const AUTOZOOM_START = 2;
const AUTOZOOM_FACTOR = 1.25;
const AUTOZOOM_MIN_PX_PER_MODULE = 3;
const AUTOZOOM_MIN_SHARE = 0.25;
const AUTOZOOM_MAX_SHARE = 0.7;
const AUTOZOOM_STREAK = 3;
const AUTOZOOM_COOLDOWN_MS = 600;
const AUTOZOOM_SETTLE_MS = 300;
const DEFAULT_ZOOM_STEP = 0.1;

const HINT_WARMUP_MS = 800;
const HINT_HOLD_MS = 400;
const HINT_MIN_DWELL_MS = 1500;
const HINT_SETTLE_MS = 300;
const HINT_WRONG_QR_MS = 3000;
const HINT_NOT_FOUND_MS = 4000;
const HINT_SHARPNESS_WINDOW_MS = 3000;
const HINT_DARK_ENTER = 40;
const HINT_DARK_EXIT = 55;
const HINT_BLUR_ENTER = 0.35;
const HINT_BLUR_EXIT = 0.5;
const HINT_MIN_PX_PER_MODULE = 3;
const HINT_MIN_SHARE = 0.25;
const HINT_MAX_SHARE = 0.7;

// Order is priority: the first active condition wins.
const HINT_PRIORITY = [
  'wrongQr',
  'dark',
  'blurry',
  'tooSmall',
  'tooLarge',
  'found',
  'notFound',
  'idle',
];
const HINT_IMMEDIATE = new Set(['wrongQr', 'notFound', 'idle']);
const HINT_MEASURED = ['dark', 'blurry', 'tooSmall', 'tooLarge'];

export function calculateCenteredScanRegion(width, height, ratio = 0.72) {
  const boundedRatio = Math.min(1, Math.max(0.1, ratio));
  const size = Math.max(1, Math.floor(Math.min(width, height) * boundedRatio));

  return {
    x: Math.floor((width - size) / 2),
    y: Math.floor((height - size) / 2),
    width: size,
    height: size,
  };
}

export function isFNSReceiptQR(rawValue) {
  if (typeof rawValue !== 'string' || !rawValue.trim()) {
    return false;
  }

  const values = new URLSearchParams(rawValue.trim());
  return REQUIRED_FNS_FIELDS.every((field) => values.get(field)?.trim());
}

export function shouldScanFullFrame(currentTime, lastFullFrameTime, interval) {
  return currentTime - lastFullFrameTime >= interval;
}

function cameraFacing(camera) {
  const facingMode = camera.capabilities?.facingMode;
  if (Array.isArray(facingMode) && facingMode.length) {
    if (facingMode.includes('environment')) {
      return 'back';
    }
    if (facingMode.includes('user')) {
      return 'front';
    }
  }
  const label = camera.label || '';
  if (/facing front/i.test(label)) {
    return 'front';
  }
  return /facing back/i.test(label) ? 'back' : null;
}

function cameraIndex(camera) {
  const match = /camera2?\s*(\d+)/i.exec(camera.label || '');
  return match ? Number(match[1]) : Infinity;
}

function cameraScore(camera) {
  const capabilities = camera.capabilities || {};
  return [
    (capabilities.focusMode || []).includes('continuous') ? 1 : 0,
    capabilities.torch === true ? 1 : 0,
    capabilities.zoom?.max || 0,
    capabilities.imageWidth?.max || 0,
    -cameraIndex(camera),
  ];
}

function compareScores(left, right) {
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) {
      return right[index] - left[index];
    }
  }
  return 0;
}

export function rankCameras(cameras) {
  return cameras
    .filter((camera) => cameraFacing(camera) === 'back')
    .map((camera, order) => ({ camera, order, score: cameraScore(camera) }))
    .sort((a, b) => compareScores(a.score, b.score) || a.order - b.order)
    .map((item) => item.camera);
}

export function pickCamera(cameras, savedDeviceId) {
  const back = cameras.filter((camera) => cameraFacing(camera) === 'back');
  if (savedDeviceId && back.some((item) => item.deviceId === savedDeviceId)) {
    return savedDeviceId;
  }
  if (!back.some((camera) => camera.capabilities)) {
    return back[0]?.deviceId ?? null;
  }
  return rankCameras(back)[0]?.deviceId ?? null;
}

export function parseQRVersion(extra) {
  if (typeof extra !== 'string' || !extra) {
    return null;
  }
  try {
    const version = Number(JSON.parse(extra).Version);
    return Number.isInteger(version) && version >= 1 && version <= 40
      ? version
      : null;
  } catch (_error) {
    return null;
  }
}

function positionBounds(position) {
  const points = [
    position.topLeft,
    position.topRight,
    position.bottomRight,
    position.bottomLeft,
  ];
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  return {
    minX: Math.min(...xs),
    maxX: Math.max(...xs),
    minY: Math.min(...ys),
    maxY: Math.max(...ys),
  };
}

export function magnificationRegion(
  position,
  version,
  frameSize,
  {
    targetPxPerModule = TARGET_PX_PER_MODULE,
    minScale = MIN_MAGNIFICATION_SCALE,
    maxScale = MAX_MAGNIFICATION_SCALE,
    maxSide = MAX_MAGNIFIED_SIDE,
    defaultVersion = DEFAULT_QR_VERSION,
    minPaddingModules = MIN_PADDING_MODULES,
    paddingRatio = PADDING_RATIO,
  } = {},
) {
  const bounds = positionBounds(position);
  const side = Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY);
  const modules = 17 + 4 * (version || defaultVersion);
  const modulePx = side / modules;
  const padding = Math.max(minPaddingModules * modulePx, paddingRatio * side);

  const x = Math.max(0, Math.floor(bounds.minX - padding));
  const y = Math.max(0, Math.floor(bounds.minY - padding));
  const right = Math.min(frameSize.width, Math.ceil(bounds.maxX + padding));
  const bottom = Math.min(frameSize.height, Math.ceil(bounds.maxY + padding));
  const width = right - x;
  const height = bottom - y;

  let scale = Math.min(
    maxScale,
    Math.max(minScale, targetPxPerModule / modulePx),
  );
  const longest = Math.max(width, height);
  if (longest * scale > maxSide) {
    scale = maxSide / longest;
  }
  return { x, y, width, height, scale };
}

function translatePosition(position, offsetX, offsetY) {
  const shift = (point) => ({ x: point.x + offsetX, y: point.y + offsetY });
  return {
    topLeft: shift(position.topLeft),
    topRight: shift(position.topRight),
    bottomRight: shift(position.bottomRight),
    bottomLeft: shift(position.bottomLeft),
  };
}

function distanceToCenter(position, frameSize) {
  const bounds = positionBounds(position);
  return Math.hypot(
    (bounds.minX + bounds.maxX) / 2 - frameSize.width / 2,
    (bounds.minY + bounds.maxY) / 2 - frameSize.height / 2,
  );
}

/**
 * Runs the passes center -> magnified center -> full frame -> magnified full
 * frame and stops at the first successful read. `decode` returns
 * `{text, position, version}` items for an image, `magnify` crops and scales
 * an image by a region. At most one magnification is made.
 */
export async function scanFrames({ frames, frameSize, decode, magnify }) {
  let magnified = false;
  let detection = null;
  let detectionDistance = Infinity;

  for (const frame of frames) {
    const results = await decode(frame.image);
    const read = results.find((item) => item.text);
    if (read) {
      return { value: read.text, detection: null, magnified };
    }

    let nearest = null;
    let nearestDistance = Infinity;
    for (const item of results) {
      if (!item.position) {
        continue;
      }
      const full = translatePosition(item.position, frame.x, frame.y);
      const distance = distanceToCenter(full, frameSize);
      if (distance < nearestDistance) {
        nearest = { item, full };
        nearestDistance = distance;
      }
      if (distance < detectionDistance) {
        detection = { position: full, version: item.version ?? null };
        detectionDistance = distance;
      }
    }

    if (nearest && !magnified) {
      magnified = true;
      const region = magnificationRegion(
        nearest.item.position,
        nearest.item.version,
        { width: frame.image.width, height: frame.image.height },
      );
      const zoomed = await decode(await magnify(frame.image, region));
      const zoomedRead = zoomed.find((item) => item.text);
      if (zoomedRead) {
        return { value: zoomedRead.text, detection: null, magnified };
      }
    }
  }
  return { value: '', detection, magnified };
}

export function zoomCorridor(capabilities) {
  const zoom = capabilities?.zoom;
  if (
    !zoom ||
    typeof zoom.min !== 'number' ||
    typeof zoom.max !== 'number' ||
    zoom.max <= zoom.min
  ) {
    return null;
  }
  const step = zoom.step > 0 ? zoom.step : DEFAULT_ZOOM_STEP;
  const steps = (value) => (value - zoom.min) / step;
  const snap = (count) => roundZoom(zoom.min + count * step);
  const min = snap(Math.ceil(steps(Math.max(AUTOZOOM_MIN, zoom.min)) - 1e-9));
  const max = snap(Math.floor(steps(Math.min(AUTOZOOM_MAX, zoom.max)) + 1e-9));
  return min > max ? null : { min, max, step, base: zoom.min };
}

function roundZoom(value) {
  return Number(value.toFixed(4));
}

function fitZoom(corridor, value) {
  const bounded = Math.min(corridor.max, Math.max(corridor.min, value));
  const steps = Math.round((bounded - corridor.base) / corridor.step);
  const snapped = roundZoom(corridor.base + steps * corridor.step);
  return Math.min(corridor.max, Math.max(corridor.min, snapped));
}

export function measureQR(detection, frameSize) {
  const bounds = positionBounds(detection.position);
  const side = Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY);
  const version = detection.version;
  return {
    pxPerModule: version ? side / (17 + 4 * version) : null,
    share: side / Math.min(frameSize.width, frameSize.height),
    center: {
      x: (bounds.minX + bounds.maxX) / 2,
      y: (bounds.minY + bounds.maxY) / 2,
    },
  };
}

export function createAutozoomState(capabilities) {
  const corridor = zoomCorridor(capabilities);
  return {
    corridor,
    zoom: corridor ? fitZoom(corridor, AUTOZOOM_START) : null,
    direction: null,
    streak: 0,
    changedAt: null,
  };
}

export function zoomLimit(state) {
  if (!state?.corridor) {
    return 'unavailable';
  }
  if (state.zoom >= state.corridor.max) {
    return 'max';
  }
  return state.zoom <= state.corridor.min ? 'min' : null;
}

function zoomDirection(measurement) {
  if (measurement.share > AUTOZOOM_MAX_SHARE) {
    return 'out';
  }
  const small =
    measurement.pxPerModule === null
      ? measurement.share < AUTOZOOM_MIN_SHARE
      : measurement.pxPerModule < AUTOZOOM_MIN_PX_PER_MODULE;
  return small ? 'in' : null;
}

export function autozoomStep(state, measurement, now) {
  if (!state.corridor) {
    return { state, zoom: null };
  }
  if (state.changedAt !== null && now - state.changedAt < AUTOZOOM_SETTLE_MS) {
    return { state, zoom: null };
  }
  const direction = measurement ? zoomDirection(measurement) : null;
  if (!direction) {
    return { state: { ...state, direction: null, streak: 0 }, zoom: null };
  }
  const streak = direction === state.direction ? state.streak + 1 : 1;
  const next = { ...state, direction, streak };
  const ready =
    streak >= AUTOZOOM_STREAK &&
    (state.changedAt === null || now - state.changedAt >= AUTOZOOM_COOLDOWN_MS);
  if (!ready) {
    return { state: next, zoom: null };
  }
  const factor = direction === 'in' ? AUTOZOOM_FACTOR : 1 / AUTOZOOM_FACTOR;
  const zoom = fitZoom(state.corridor, state.zoom * factor);
  if (zoom === state.zoom) {
    return { state: { ...next, streak: 0 }, zoom: null };
  }
  return {
    state: { ...next, zoom, streak: 0, changedAt: now },
    zoom,
  };
}

export function createScanHints(now) {
  return {
    startedAt: now,
    active: {},
    since: {},
    samples: [],
    relativeSharpness: 1,
    lastQrAt: now,
    wrongQrUntil: -Infinity,
    settleUntil: -Infinity,
    shown: { id: 'idle', since: -Infinity },
  };
}

function hintKey(id, observation) {
  if (id === 'dark') {
    const torch = observation.torch;
    return torch?.available && !torch.on ? 'darkTorch' : 'dark';
  }
  return id;
}

/**
 * Live hint reducer. `observation`:
 * `{brightness, sharpness, qr: {pxPerModule, share} | null,
 *   wrongQr: boolean, zoomStepped: boolean,
 *   zoom: {available, atMin, atMax}, torch: {available, on}}`
 * where `wrongQr` means a non-receipt QR was read in this very frame.
 * Returns `{state, hint: {id, key}}`.
 */
export function scanHints(state, observation, now) {
  const qr = observation.qr;
  const zoom = observation.zoom || { available: false };
  const settleUntil = observation.zoomStepped
    ? now + HINT_SETTLE_MS
    : state.settleUntil;
  const settling = now < settleUntil;
  const wrongQrUntil = observation.wrongQr
    ? now + HINT_WRONG_QR_MS
    : state.wrongQrUntil;

  let samples = state.samples;
  let relativeSharpness = state.relativeSharpness;
  if (!settling) {
    samples = [
      ...samples.filter((item) => now - item.at < HINT_SHARPNESS_WINDOW_MS),
      { at: now, value: observation.sharpness },
    ];
    const peak = Math.max(...samples.map((item) => item.value));
    relativeSharpness = peak > 0 ? observation.sharpness / peak : 1;
  }

  const was = state.active;
  let measured;
  if (settling) {
    measured = {};
    for (const id of HINT_MEASURED) {
      measured[id] = Boolean(was[id]);
    }
  } else {
    const small =
      qr &&
      (qr.pxPerModule != null
        ? qr.pxPerModule < HINT_MIN_PX_PER_MODULE
        : qr.share < HINT_MIN_SHARE);
    measured = {
      dark: was.dark
        ? observation.brightness <= HINT_DARK_EXIT
        : observation.brightness < HINT_DARK_ENTER,
      blurry: was.blurry
        ? relativeSharpness <= HINT_BLUR_EXIT
        : relativeSharpness < HINT_BLUR_ENTER,
      tooSmall: Boolean(small) && (!zoom.available || zoom.atMax === true),
      tooLarge:
        Boolean(qr) &&
        qr.share > HINT_MAX_SHARE &&
        (!zoom.available || zoom.atMin === true),
    };
  }

  const lastQrAt = qr || observation.wrongQr ? now : state.lastQrAt;
  const active = {
    wrongQr: now < wrongQrUntil,
    ...measured,
    found: Boolean(qr),
    notFound: !qr && now - lastQrAt >= HINT_NOT_FOUND_MS,
    idle: true,
  };
  const since = {};
  for (const id of HINT_PRIORITY) {
    since[id] = active[id] ? (state.since[id] ?? now) : null;
  }

  const warm = now - state.startedAt < HINT_WARMUP_MS;
  const candidate = HINT_PRIORITY.find(
    (id) =>
      active[id] &&
      (HINT_IMMEDIATE.has(id) || (!warm && now - since[id] >= HINT_HOLD_MS)),
  );

  let shown = state.shown;
  if (
    candidate !== shown.id &&
    (candidate === 'wrongQr' || now - shown.since >= HINT_MIN_DWELL_MS)
  ) {
    shown = { id: candidate, since: now };
  }

  return {
    state: {
      ...state,
      active,
      since,
      samples,
      relativeSharpness,
      lastQrAt,
      wrongQrUntil,
      settleUntil,
      shown,
    },
    hint: { id: shown.id, key: hintKey(shown.id, observation) },
  };
}

const METRICS_STEP = 4;

/**
 * Mean brightness (0-255) and variance of the Laplacian over RGBA pixel data,
 * sampled on a grid with a step of 4 pixels.
 */
export function frameMetrics({ data, width, height }) {
  const luma = (x, y) => {
    const offset = (y * width + x) * 4;
    return (
      0.299 * data[offset] + 0.587 * data[offset + 1] + 0.114 * data[offset + 2]
    );
  };
  let brightnessSum = 0;
  let brightnessCount = 0;
  let laplacianSum = 0;
  let laplacianSquares = 0;
  let laplacianCount = 0;
  for (let y = METRICS_STEP; y < height - METRICS_STEP; y += METRICS_STEP) {
    for (let x = METRICS_STEP; x < width - METRICS_STEP; x += METRICS_STEP) {
      const center = luma(x, y);
      brightnessSum += center;
      brightnessCount += 1;
      const laplacian =
        luma(x - METRICS_STEP, y) +
        luma(x + METRICS_STEP, y) +
        luma(x, y - METRICS_STEP) +
        luma(x, y + METRICS_STEP) -
        4 * center;
      laplacianSum += laplacian;
      laplacianSquares += laplacian * laplacian;
      laplacianCount += 1;
    }
  }
  if (!brightnessCount) {
    return { brightness: 0, sharpness: 0 };
  }
  const mean = laplacianSum / laplacianCount;
  return {
    brightness: brightnessSum / brightnessCount,
    sharpness: laplacianSquares / laplacianCount - mean * mean,
  };
}
