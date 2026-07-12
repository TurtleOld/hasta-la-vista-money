const REQUIRED_FNS_FIELDS = ['t', 's', 'fn', 'i', 'fp', 'n'];

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
