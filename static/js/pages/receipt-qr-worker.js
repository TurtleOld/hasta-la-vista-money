import { prepareZXingModule, readBarcodes } from 'zxing-wasm/reader';

import {
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

async function decodeImage(image) {
  const results = await readBarcodes(image, READER_OPTIONS);
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

self.addEventListener('message', async (event) => {
  const { type } = event.data;

  if (type === 'initialize') {
    try {
      await initializeDecoder(event.data.wasmUrl);
      self.postMessage({ type: 'ready' });
    } catch (error) {
      self.postMessage({
        type: 'initialize-error',
        message: error instanceof Error ? error.message : String(error),
      });
    }
    return;
  }

  if (type !== 'scan') {
    return;
  }

  try {
    await decoderReady;
    let decodeMs = 0;
    const result = await scanFrames({
      frames: event.data.frames,
      frameSize: {
        width: event.data.frameWidth,
        height: event.data.frameHeight,
      },
      decode: async (image) => {
        const startedAt = performance.now();
        try {
          return await decodeImage(image);
        } finally {
          decodeMs += performance.now() - startedAt;
        }
      },
      magnify: magnifyImage,
    });
    const metrics = frameMetrics(event.data.frames[0].image);
    self.postMessage({ type: 'scan-result', ...result, ...metrics, decodeMs });
  } catch (error) {
    self.postMessage({
      type: 'scan-error',
      message: error instanceof Error ? error.message : String(error),
    });
  }
});
