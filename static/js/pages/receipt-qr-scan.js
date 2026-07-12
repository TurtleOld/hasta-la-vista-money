import {
  calculateCenteredScanRegion,
  isFNSReceiptQR,
  shouldScanFullFrame,
} from '../receipt-qr-core.mjs';

const SCAN_INTERVAL_MS = 120;
const FULL_FRAME_INTERVAL_MS = 1000;
const WORKER_START_TIMEOUT_MS = 10000;

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
    invalidQR: element.dataset.messageInvalidQr,
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
      statusMessage: '',
      stream: null,
      worker: null,
      workerBusy: false,
      scanTimer: null,
      lastFullFrameTime: 0,
      torchAvailable: false,
      torchEnabled: false,
      zoomAvailable: false,
      zoomMin: 1,
      zoomMax: 1,
      zoomStep: 0.1,
      zoomValue: 1,

      init() {
        this.messages = messagesFrom(this.$el);
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

      async start() {
        this.errorMessage = '';
        this.noticeMessage = '';
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
          this.stream = await navigator.mediaDevices.getUserMedia({
            video: {
              facingMode: { ideal: 'environment' },
              width: { ideal: 1920 },
              height: { ideal: 1080 },
              resizeMode: { ideal: 'crop-and-scale' },
            },
          });
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

        if (message.type === 'scan-error') {
          console.warn(
            'receipt QR scan: frame decoding failed',
            message.message,
          );
          this.scheduleScan();
          return;
        }
        if (!message.value) {
          this.scheduleScan();
          return;
        }
        if (!isFNSReceiptQR(message.value)) {
          this.noticeMessage = this.messages.invalidQR;
          this.scheduleScan(500);
          return;
        }
        this.submitDecoded(message.value);
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
        const zoom = capabilities.zoom;
        if (
          zoom &&
          typeof zoom.min === 'number' &&
          typeof zoom.max === 'number' &&
          zoom.max > zoom.min
        ) {
          const settings = track.getSettings?.() || {};
          this.zoomAvailable = true;
          this.zoomMin = zoom.min;
          this.zoomMax = zoom.max;
          this.zoomStep = zoom.step || 0.1;
          this.zoomValue = settings.zoom || zoom.min;
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

      async applyZoom() {
        const track = this.getVideoTrack();
        if (!track || !this.zoomAvailable) {
          return;
        }
        const zoom = Number(this.zoomValue);
        try {
          await track.applyConstraints({ advanced: [{ zoom }] });
        } catch (error) {
          console.warn('receipt QR scan: zoom unavailable', error);
        }
      },

      zoomLabel() {
        return `${Number(this.zoomValue).toFixed(1)}×`;
      },

      async focusAt(event) {
        if (event.target.closest('.receipts-scan-controls')) {
          return;
        }
        const track = this.getVideoTrack();
        const video = this.$refs.video;
        if (!track?.getCapabilities || !video) {
          return;
        }
        let capabilities;
        try {
          capabilities = track.getCapabilities();
        } catch (_error) {
          return;
        }
        if (!capabilities.pointsOfInterest) {
          return;
        }
        const rect = video.getBoundingClientRect();
        const point = {
          x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
          y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
        };
        const advanced = { pointsOfInterest: [point] };
        if ((capabilities.focusMode || []).includes('single-shot')) {
          advanced.focusMode = 'single-shot';
        }
        try {
          await track.applyConstraints({ advanced: [advanced] });
        } catch (error) {
          console.warn('receipt QR scan: point focus unavailable', error);
        }
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
        const context = canvas.getContext('2d', { willReadFrequently: true });
        context.drawImage(video, 0, 0, canvas.width, canvas.height);

        const region = calculateCenteredScanRegion(canvas.width, canvas.height);
        const frames = [
          context.getImageData(region.x, region.y, region.width, region.height),
        ];
        const now = performance.now();
        if (
          shouldScanFullFrame(
            now,
            this.lastFullFrameTime,
            FULL_FRAME_INTERVAL_MS,
          )
        ) {
          frames.push(context.getImageData(0, 0, canvas.width, canvas.height));
          this.lastFullFrameTime = now;
        }

        this.workerBusy = true;
        this.noticeMessage = '';
        const transfer = frames.map((frame) => frame.data.buffer);
        this.worker.postMessage({ type: 'scan', frames }, transfer);
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
        this.zoomAvailable = false;
        this.statusMessage = '';
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
