import { prepareZXingModule, readBarcodes } from 'zxing-wasm/reader';

const READER_OPTIONS = {
  formats: ['QRCode'],
  maxNumberOfSymbols: 1,
  binarizer: 'LocalAverage',
  tryHarder: true,
  tryRotate: true,
  tryInvert: true,
  tryDownscale: true,
  tryDenoise: true,
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

async function decodeFrames(frames) {
  for (const frame of frames) {
    const results = await readBarcodes(frame, READER_OPTIONS);
    const result = results.find((item) => item.text);
    if (result) {
      return result.text;
    }
  }
  return '';
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
    const value = await decodeFrames(event.data.frames);
    self.postMessage({ type: 'scan-result', value });
  } catch (error) {
    self.postMessage({
      type: 'scan-error',
      message: error instanceof Error ? error.message : String(error),
    });
  }
});
