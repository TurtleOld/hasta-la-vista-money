import {
  autozoomStep,
  calculateCenteredScanRegion,
  createAutozoomState,
  createScanHints,
  isFNSReceiptQR,
  measureQR,
  pickCamera,
  scanHints,
  shouldScanFullFrame,
  zoomLimit,
} from '../receipt-qr-core.mjs';

const SCAN_INTERVAL_MS = 120;
const FULL_FRAME_INTERVAL_MS = 1000;
const WRONG_QR_RESCAN_DELAY_MS = 500;
const WORKER_START_TIMEOUT_MS = 10000;
const TAP_POINT_TTL_MS = 3000;
const CAMERA_STORAGE_KEY = 'receiptQRScanCameraId';
const IDEAL_WIDTH = 1920;
const IDEAL_HEIGHT = 1080;
const CAMERA_MISSING_ERRORS = ['NotFoundError', 'OverconstrainedError'];

function readSavedCameraId() {
  try {
    return window.localStorage.getItem(CAMERA_STORAGE_KEY);
  } catch (_error) {
    return null;
  }
}

function saveCameraId(deviceId) {
  try {
    window.localStorage.setItem(CAMERA_STORAGE_KEY, deviceId);
  } catch (_error) {
    // Storage may be unavailable (private mode); the choice is just not kept.
  }
}

function forgetCameraId() {
  try {
    window.localStorage.removeItem(CAMERA_STORAGE_KEY);
  } catch (_error) {
    // Nothing to forget when storage is unavailable.
  }
}

function videoConstraints(deviceId) {
  return {
    video: {
      ...(deviceId
        ? { deviceId: { exact: deviceId } }
        : { facingMode: { ideal: 'environment' } }),
      width: { ideal: IDEAL_WIDTH },
      height: { ideal: IDEAL_HEIGHT },
      resizeMode: { ideal: 'crop-and-scale' },
    },
  };
}

function safeCapabilities(track) {
  try {
    return track.getCapabilities?.() || null;
  } catch (_error) {
    return null;
  }
}

function hasContinuousFocus(stream) {
  const capabilities = safeCapabilities(stream.getVideoTracks()[0]);
  return (capabilities?.focusMode || []).includes('continuous');
}

async function probeBackCameras() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const cameras = [];
  for (const device of devices) {
    if (device.kind !== 'videoinput' || !device.deviceId) {
      continue;
    }
    let probe = null;
    try {
      probe = await navigator.mediaDevices.getUserMedia({
        video: { deviceId: { exact: device.deviceId } },
      });
      cameras.push({
        deviceId: device.deviceId,
        label: device.label,
        capabilities: safeCapabilities(probe.getVideoTracks()[0]),
      });
    } catch (error) {
      console.warn('receipt QR scan: camera probe failed', error);
    } finally {
      probe?.getTracks().forEach((track) => track.stop());
    }
  }
  return cameras;
}

async function openStream() {
  const savedId = readSavedCameraId();
  if (savedId) {
    try {
      const stream = await navigator.mediaDevices.getUserMedia(
        videoConstraints(savedId),
      );
      if (hasContinuousFocus(stream)) {
        return stream;
      }
      stream.getTracks().forEach((track) => track.stop());
    } catch (error) {
      if (!CAMERA_MISSING_ERRORS.includes(error?.name)) {
        throw error;
      }
    }
    forgetCameraId();
  }

  // Labels and capabilities are only readable after permission is granted.
  const primer = await navigator.mediaDevices.getUserMedia(
    videoConstraints(null),
  );
  primer.getTracks().forEach((track) => track.stop());

  let deviceId = null;
  try {
    deviceId = pickCamera(await probeBackCameras(), null);
  } catch (error) {
    console.warn('receipt QR scan: camera discovery failed', error);
  }
  if (!deviceId) {
    return navigator.mediaDevices.getUserMedia(videoConstraints(null));
  }
  const stream = await navigator.mediaDevices.getUserMedia(
    videoConstraints(deviceId),
  );
  saveCameraId(deviceId);
  return stream;
}

function messagesFrom(element) {
  return {
    cameraUnavailable: element.dataset.messageCameraUnavailable,
    cameraPolicyBlocked: element.dataset.messageCameraPolicyBlocked,
    cameraDenied: element.dataset.messageCameraDenied,
    cameraNotFound: element.dataset.messageCameraNotFound,
    cameraBusy: element.dataset.messageCameraBusy,
    cameraConstraints: element.dataset.messageCameraConstraints,
    cameraGeneric: element.dataset.messageCameraGeneric,
    decoderUnavailable: element.dataset.messageDecoderUnavailable,
    hints: {
      wrongQr: element.dataset.hintWrongQr,
      dark: element.dataset.hintDark,
      darkTorch: element.dataset.hintDarkTorch,
      blurry: element.dataset.hintBlurry,
      tooSmall: element.dataset.hintTooSmall,
      tooLarge: element.dataset.hintTooLarge,
      found: element.dataset.hintFound,
      notFound: element.dataset.hintNotFound,
      idle: element.dataset.hintIdle,
    },
    preparing: element.dataset.messagePreparing,
    scanning: element.dataset.messageScanning,
  };
}

function describeCameraError(error, messages) {
  const name = error && error.name;
  const message = (error && error.message) || '';

  if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
    return /permissions policy/i.test(message)
      ? messages.cameraPolicyBlocked
      : messages.cameraDenied;
  }
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
    return messages.cameraNotFound;
  }
  if (name === 'NotReadableError' || name === 'TrackStartError') {
    return messages.cameraBusy;
  }
  if (
    name === 'OverconstrainedError' ||
    name === 'ConstraintNotSatisfiedError'
  ) {
    return messages.cameraConstraints;
  }
  if (name === 'SecurityError') {
    return messages.cameraPolicyBlocked;
  }
  return messages.cameraGeneric;
}

function registerReceiptUploadTabs(Alpine) {
  Alpine.data('receiptUploadTabs', function () {
    return {
      activeTab: 'file',

      init() {
        document.addEventListener('receipt-upload:file-pasted', () => {
          if (this.activeTab !== 'file') {
            this.selectFile();
          }
        });
      },

      selectFile() {
        this.activeTab = 'file';
        document.dispatchEvent(new CustomEvent('receipt-scan:deactivate'));
      },

      selectScan() {
        this.activeTab = 'scan';
        document.dispatchEvent(new CustomEvent('receipt-scan:activate'));
      },
    };
  });
}

function registerReceiptQRScanPage(Alpine) {
  Alpine.data('receiptQRScanPage', function () {
    return {
      errorMessage: '',
      noticeMessage: '',
      noticeLink: '',
      statusMessage: '',
      hintText: '',
      hintState: null,
      zoomStepped: false,
      stream: null,
      worker: null,
      workerBusy: false,
      scanTimer: null,
      lastFullFrameTime: 0,
      lastTapPoint: null,
      lastTapTime: 0,
      torchAvailable: false,
      torchEnabled: false,
      autozoom: null,
      frameSize: null,
      zoomLimit: 'unavailable',

      init() {
        this.messages = messagesFrom(this.$el);
        this.pollNotifications();
        window.setInterval(() => this.pollNotifications(), 5000);
        document.addEventListener(
          'receipt-scan:activate',
          this.start.bind(this),
        );
        document.addEventListener(
          'receipt-scan:deactivate',
          this.stop.bind(this),
        );
        window.addEventListener('beforeunload', this.stop.bind(this));
      },

      async pollNotifications() {
        const notificationsUrl = this.$el.dataset.notificationsUrl;
        if (!notificationsUrl) {
          return;
        }
        try {
          const response = await fetch(notificationsUrl, {
            headers: { Accept: 'application/json' },
            credentials: 'same-origin',
          });
          const payload = await response.json();
          const notification = payload.notifications?.[0];
          if (notification) {
            this.noticeMessage = notification.message;
            this.noticeLink = notification.url;
          }
        } catch (error) {
          console.warn('receipt QR scan: notification polling failed', error);
        }
      },

      async start() {
        this.errorMessage = '';
        this.noticeMessage = '';
        this.noticeLink = '';
        if (this.stream) {
          return;
        }
        if (
          !window.Worker ||
          !window.WebAssembly ||
          !navigator.mediaDevices?.getUserMedia
        ) {
          this.errorMessage = this.messages.cameraUnavailable;
          return;
        }

        this.statusMessage = this.messages.preparing;
        try {
          await this.initializeWorker();
        } catch (error) {
          console.error('receipt QR scan: decoder startup failed', error);
          this.errorMessage = this.messages.decoderUnavailable;
          this.stop({ preserveError: true });
          return;
        }

        try {
          this.stream = await openStream();
        } catch (error) {
          console.error('receipt QR scan: camera startup failed', error);
          this.errorMessage = describeCameraError(error, this.messages);
          this.stop({ preserveError: true });
          return;
        }

        await this.configureCamera();
        const video = this.$refs.video;
        if (!video) {
          this.stop();
          return;
        }
        video.srcObject = this.stream;
        try {
          await video.play();
        } catch (error) {
          console.error('receipt QR scan: video playback failed', error);
          this.errorMessage = this.messages.cameraGeneric;
          this.stop({ preserveError: true });
          return;
        }
        this.statusMessage = this.messages.scanning;
        this.hintState = createScanHints(performance.now());
        this.hintText = this.messages.hints.idle;
        this.scheduleScan(0);
      },

      initializeWorker() {
        return new Promise((resolve, reject) => {
          const workerUrl = this.$el.dataset.workerUrl;
          const wasmUrl = this.$el.dataset.wasmUrl;
          const timeout = window.setTimeout(() => {
            reject(new Error('QR decoder worker start timed out'));
          }, WORKER_START_TIMEOUT_MS);

          try {
            this.worker = new Worker(workerUrl);
          } catch (error) {
            window.clearTimeout(timeout);
            reject(error);
            return;
          }

          this.worker.addEventListener('message', (event) => {
            if (event.data.type === 'ready') {
              window.clearTimeout(timeout);
              resolve();
              return;
            }
            if (event.data.type === 'initialize-error') {
              window.clearTimeout(timeout);
              reject(new Error(event.data.message));
              return;
            }
            this.handleWorkerMessage(event.data);
          });
          this.worker.addEventListener('error', (event) => {
            window.clearTimeout(timeout);
            reject(event.error || new Error(event.message));
          });
          this.worker.postMessage({ type: 'initialize', wasmUrl });
        });
      },

      handleWorkerMessage(message) {
        if (message.type !== 'scan-result' && message.type !== 'scan-error') {
          return;
        }
        this.workerBusy = false;

        if (message.type === 'scan-result' && !message.value) {
          this.runAutozoom(message.detection);
        }
        if (message.type === 'scan-error') {
          console.warn(
            'receipt QR scan: frame decoding failed',
            message.message,
          );
          this.scheduleScan();
          return;
        }
        const wrongQr =
          Boolean(message.value) && !isFNSReceiptQR(message.value);
        this.updateHint(message, wrongQr);
        if (!message.value || wrongQr) {
          this.scheduleScan(wrongQr ? WRONG_QR_RESCAN_DELAY_MS : undefined);
          return;
        }
        this.submitDecoded(message.value);
      },

      updateHint(message, wrongQr) {
        if (!this.hintState) {
          return;
        }
        const result = scanHints(
          this.hintState,
          {
            brightness: message.brightness,
            sharpness: message.sharpness,
            qr:
              message.detection && this.frameSize
                ? measureQR(message.detection, this.frameSize)
                : null,
            wrongQr,
            zoomStepped: this.zoomStepped,
            zoom: {
              available: this.zoomLimit !== 'unavailable',
              atMin: this.zoomLimit === 'min',
              atMax: this.zoomLimit === 'max',
            },
            torch: { available: this.torchAvailable, on: this.torchEnabled },
          },
          performance.now(),
        );
        this.zoomStepped = false;
        this.hintState = result.state;
        this.hintText = this.messages.hints[result.hint.key];
      },

      async configureCamera() {
        const track = this.getVideoTrack();
        if (!track?.getCapabilities) {
          return;
        }
        let capabilities;
        try {
          capabilities = track.getCapabilities();
        } catch (_error) {
          return;
        }

        this.torchAvailable = capabilities.torch === true;
        this.autozoom = createAutozoomState(capabilities);
        this.zoomLimit = zoomLimit(this.autozoom);
        if (this.autozoom.zoom !== null) {
          await this.applyZoom(this.autozoom.zoom);
        }

        const focusModes = capabilities.focusMode || [];
        if (focusModes.includes('continuous')) {
          try {
            await track.applyConstraints({
              advanced: [{ focusMode: 'continuous' }],
            });
          } catch (error) {
            console.warn(
              'receipt QR scan: continuous focus unavailable',
              error,
            );
          }
        }
      },

      getVideoTrack() {
        return this.stream?.getVideoTracks()[0] || null;
      },

      async toggleTorch() {
        const track = this.getVideoTrack();
        if (!track || !this.torchAvailable) {
          return;
        }
        const nextValue = !this.torchEnabled;
        try {
          await track.applyConstraints({ advanced: [{ torch: nextValue }] });
          this.torchEnabled = nextValue;
        } catch (error) {
          console.warn('receipt QR scan: torch unavailable', error);
        }
      },

      async applyZoom(zoom) {
        const track = this.getVideoTrack();
        if (!track) {
          return false;
        }
        try {
          await track.applyConstraints({ advanced: [{ zoom }] });
          return true;
        } catch (error) {
          console.warn('receipt QR scan: zoom unavailable', error);
          return false;
        }
      },

      async runAutozoom(detection) {
        if (!this.autozoom || !this.frameSize) {
          return;
        }
        const frameSize = this.frameSize;
        const measurement = detection ? measureQR(detection, frameSize) : null;
        const now = performance.now();
        const step = autozoomStep(this.autozoom, measurement, now);
        this.autozoom = step.state;
        this.zoomLimit = zoomLimit(step.state);
        if (step.zoom === null) {
          return;
        }
        this.zoomStepped = true;
        await this.applyZoom(step.zoom);
        const tapIsFresh =
          this.lastTapPoint && now - this.lastTapTime < TAP_POINT_TTL_MS;
        if (tapIsFresh) {
          await this.applyPointOfInterest(this.lastTapPoint);
        } else if (measurement) {
          await this.applyPointOfInterest({
            x: measurement.center.x / frameSize.width,
            y: measurement.center.y / frameSize.height,
          });
        }
      },

      async applyPointOfInterest(point) {
        const track = this.getVideoTrack();
        if (
          !track ||
          !navigator.mediaDevices.getSupportedConstraints().pointsOfInterest
        ) {
          return;
        }
        try {
          await track.applyConstraints({
            advanced: [{ pointsOfInterest: [point] }],
          });
        } catch (error) {
          console.warn('receipt QR scan: point focus unavailable', error);
        }
      },

      async focusAt(event) {
        if (event.target.closest('.receipts-scan-controls')) {
          return;
        }
        const track = this.getVideoTrack();
        const video = this.$refs.video;
        if (!track || !video) {
          return;
        }
        if (
          !navigator.mediaDevices.getSupportedConstraints().pointsOfInterest
        ) {
          return;
        }
        const rect = video.getBoundingClientRect();
        const point = {
          x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
          y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
        };
        this.lastTapPoint = point;
        this.lastTapTime = performance.now();
        await this.applyPointOfInterest(point);
      },

      scheduleScan(delay = SCAN_INTERVAL_MS) {
        if (!this.stream || !this.worker) {
          return;
        }
        window.clearTimeout(this.scanTimer);
        this.scanTimer = window.setTimeout(this.scanFrame.bind(this), delay);
      },

      scanFrame() {
        const video = this.$refs.video;
        const canvas = this.$refs.canvas;
        if (
          !video ||
          !canvas ||
          !this.worker ||
          this.workerBusy ||
          video.readyState < video.HAVE_CURRENT_DATA
        ) {
          this.scheduleScan();
          return;
        }

        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        this.frameSize = { width: canvas.width, height: canvas.height };
        const context = canvas.getContext('2d', { willReadFrequently: true });
        context.drawImage(video, 0, 0, canvas.width, canvas.height);

        const region = calculateCenteredScanRegion(canvas.width, canvas.height);
        const frames = [
          {
            image: context.getImageData(
              region.x,
              region.y,
              region.width,
              region.height,
            ),
            x: region.x,
            y: region.y,
          },
        ];
        const now = performance.now();
        if (
          shouldScanFullFrame(
            now,
            this.lastFullFrameTime,
            FULL_FRAME_INTERVAL_MS,
          )
        ) {
          frames.push({
            image: context.getImageData(0, 0, canvas.width, canvas.height),
            x: 0,
            y: 0,
          });
          this.lastFullFrameTime = now;
        }

        this.workerBusy = true;
        this.noticeMessage = '';
        const transfer = frames.map((frame) => frame.image.data.buffer);
        this.worker.postMessage(
          {
            type: 'scan',
            frames,
            frameWidth: canvas.width,
            frameHeight: canvas.height,
          },
          transfer,
        );
      },

      submitDecoded(rawValue) {
        this.stop();
        const form = this.$refs.scanForm;
        const qrInput = form?.querySelector('[name="qr_raw"]');
        if (qrInput) {
          qrInput.value = rawValue;
        }
        form?.submit();
      },

      stop({ preserveError = false } = {}) {
        window.clearTimeout(this.scanTimer);
        this.scanTimer = null;
        this.stream?.getTracks().forEach((track) => track.stop());
        this.stream = null;
        this.worker?.terminate();
        this.worker = null;
        this.workerBusy = false;
        this.torchAvailable = false;
        this.torchEnabled = false;
        this.autozoom = null;
        this.frameSize = null;
        this.zoomLimit = 'unavailable';
        this.statusMessage = '';
        this.hintText = '';
        this.hintState = null;
        this.zoomStepped = false;
        if (!preserveError) {
          this.errorMessage = '';
        }
      },
    };
  });
}

if (window.Alpine) {
  registerReceiptUploadTabs(window.Alpine);
  registerReceiptQRScanPage(window.Alpine);
} else {
  document.addEventListener('alpine:init', function () {
    registerReceiptUploadTabs(window.Alpine);
    registerReceiptQRScanPage(window.Alpine);
  });
}
