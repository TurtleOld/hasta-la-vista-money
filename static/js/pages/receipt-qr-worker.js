import { prepareZXingModule, readBarcodes } from 'zxing-wasm/reader';

import {
  PHOTO_MAGNIFICATION,
  frameMetrics,
  parseQRVersion,
  scanFrames,
} from '../receipt-qr-core.mjs';

const READER_OPTIONS = {
  formats: ['QRCode'],
  returnErrors: true,
  maxNumberOfSymbols: 2,
  binarizer: 'LocalAverage',
  tryHarder: true,
  tryRotate: false,
  tryInvert: true,
  tryDownscale: true,
  tryDenoise: false,
  textMode: 'Plain',
};

let decoderReady = null;

function initializeDecoder(wasmUrl) {
  if (!decoderReady) {
    decoderReady = prepareZXingModule({
      overrides: {
        locateFile(path, prefix) {
          return path.endsWith('.wasm') ? wasmUrl : prefix + path;
        },
      },
      fireImmediately: true,
    });
  }
  return decoderReady;
}

async function decodeImage(image, options = READER_OPTIONS) {
  const results = await readBarcodes(image, options);
  return results.map((result) => ({
    text: result.isValid === false ? '' : result.text,
    position: result.position,
    version: parseQRVersion(result.extra),
  }));
}

function magnifyImage(image, region) {
  const source = new OffscreenCanvas(image.width, image.height);
  source.getContext('2d').putImageData(image, 0, 0);

  const width = Math.max(1, Math.round(region.width * region.scale));
  const height = Math.max(1, Math.round(region.height * region.scale));
  const target = new OffscreenCanvas(width, height);
  const context = target.getContext('2d', { willReadFrequently: true });
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = 'high';
  context.drawImage(
    source,
    region.x,
    region.y,
    region.width,
    region.height,
    0,
    0,
    width,
    height,
  );
  return context.getImageData(0, 0, width, height);
}

async function scanImages({
  frames,
  frameWidth,
  frameHeight,
  options,
  regionOptions,
}) {
  await decoderReady;
  let decodeMs = 0;
  const result = await scanFrames({
    frames,
    frameSize: { width: frameWidth, height: frameHeight },
    regionOptions,
    decode: async (image) => {
      const startedAt = performance.now();
      try {
        return await decodeImage(image, options);
      } finally {
        decodeMs += performance.now() - startedAt;
      }
    },
    magnify: magnifyImage,
  });
  const metrics = frameMetrics(frames[0].image);
  return { type: 'scan-result', ...result, ...metrics, decodeMs };
}

async function photoToImageData(blob) {
  const bitmap = await createImageBitmap(blob);
  try {
    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
    const context = canvas.getContext('2d', { willReadFrequently: true });
    context.drawImage(bitmap, 0, 0);
    return context.getImageData(0, 0, bitmap.width, bitmap.height);
  } finally {
    bitmap.close();
  }
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

self.addEventListener('message', async (event) => {
  const { type } = event.data;

  if (type === 'initialize') {
    try {
      await initializeDecoder(event.data.wasmUrl);
      self.postMessage({ type: 'ready' });
    } catch (error) {
      self.postMessage({
        type: 'initialize-error',
        message: errorMessage(error),
      });
    }
    return;
  }

  if (type === 'scan') {
    try {
      self.postMessage(
        await scanImages({
          frames: event.data.frames,
          frameWidth: event.data.frameWidth,
          frameHeight: event.data.frameHeight,
          options: READER_OPTIONS,
        }),
      );
    } catch (error) {
      self.postMessage({ type: 'scan-error', message: errorMessage(error) });
    }
    return;
  }

  if (type === 'scan-photo') {
    try {
      const image = await photoToImageData(event.data.blob);
      const result = await scanImages({
        frames: [{ image, x: 0, y: 0 }],
        frameWidth: image.width,
        frameHeight: image.height,
        options: { ...READER_OPTIONS, tryDownscale: true },
        regionOptions: PHOTO_MAGNIFICATION,
      });
      self.postMessage({ ...result, source: 'photo' });
    } catch (error) {
      self.postMessage({
        type: 'scan-error',
        source: 'photo',
        message: errorMessage(error),
      });
    }
  }
});
