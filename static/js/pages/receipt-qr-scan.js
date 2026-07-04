import jsQR from 'jsqr';

const SCAN_INTERVAL_MS = 200;
const CAMERA_UNAVAILABLE_MESSAGE = 'Камера недоступна в этом браузере.';
const CAMERA_POLICY_BLOCKED_MESSAGE =
  'Доступ к камере заблокирован настройками сайта (Permissions-Policy). Используйте загрузку файла.';
const CAMERA_DENIED_MESSAGE =
  'Доступ к камере запрещён. Разрешите доступ в настройках браузера или используйте загрузку файла.';
const CAMERA_NOT_FOUND_MESSAGE =
  'Камера не найдена на этом устройстве. Используйте загрузку файла.';
const CAMERA_BUSY_MESSAGE =
  'Камера уже используется другим приложением. Используйте загрузку файла.';
const CAMERA_CONSTRAINTS_MESSAGE =
  'Не удалось подключиться к камере с нужными параметрами. Используйте загрузку файла.';
const CAMERA_GENERIC_ERROR_MESSAGE =
  'Не удалось получить доступ к камере. Используйте загрузку файла.';

function describeCameraError(error) {
  const name = error && error.name;
  const message = (error && error.message) || '';

  if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
    return /permissions policy/i.test(message)
      ? CAMERA_POLICY_BLOCKED_MESSAGE
      : CAMERA_DENIED_MESSAGE;
  }
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
    return CAMERA_NOT_FOUND_MESSAGE;
  }
  if (name === 'NotReadableError' || name === 'TrackStartError') {
    return CAMERA_BUSY_MESSAGE;
  }
  if (
    name === 'OverconstrainedError' ||
    name === 'ConstraintNotSatisfiedError'
  ) {
    return CAMERA_CONSTRAINTS_MESSAGE;
  }
  if (name === 'SecurityError') {
    return CAMERA_POLICY_BLOCKED_MESSAGE;
  }
  return CAMERA_GENERIC_ERROR_MESSAGE;
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
      stream: null,
      scanTimer: null,

      init() {
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
        if (this.stream) {
          return;
        }
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
          this.errorMessage = CAMERA_UNAVAILABLE_MESSAGE;
          return;
        }
        try {
          this.stream = await navigator.mediaDevices.getUserMedia({
            video: {
              facingMode: 'environment',
              width: { ideal: 1920 },
              height: { ideal: 1080 },
              advanced: [{ focusMode: 'continuous' }],
            },
          });
        } catch (error) {
          console.error('receipt QR scan: camera access failed', error);
          this.errorMessage = describeCameraError(error);
          return;
        }
        await this.applyFocusConstraints();
        await this.applyZoomConstraint();
        const video = this.$refs.video;
        if (!video) {
          this.stop();
          return;
        }
        video.srcObject = this.stream;
        await video.play();
        this.scanTimer = window.setInterval(
          this.scanFrame.bind(this),
          SCAN_INTERVAL_MS,
        );
      },

      async applyFocusConstraints() {
        const track = this.stream && this.stream.getVideoTracks()[0];
        if (!track || typeof track.getCapabilities !== 'function') {
          return;
        }
        let capabilities;
        try {
          capabilities = track.getCapabilities();
        } catch (_error) {
          return;
        }
        if (!capabilities || !capabilities.focusMode) {
          return;
        }
        const focusModes = capabilities.focusMode;
        const advanced = {};
        if (focusModes.includes('continuous')) {
          advanced.focusMode = 'continuous';
        } else if (focusModes.includes('single-shot')) {
          advanced.focusMode = 'single-shot';
        }
        if (Object.keys(advanced).length === 0) {
          return;
        }
        try {
          await track.applyConstraints({ advanced: [advanced] });
        } catch (error) {
          console.warn(
            'receipt QR scan: failed to apply focus constraints',
            error,
          );
        }
      },

      async applyZoomConstraint() {
        const track = this.stream && this.stream.getVideoTracks()[0];
        if (!track || typeof track.getCapabilities !== 'function') {
          return;
        }
        let capabilities;
        try {
          capabilities = track.getCapabilities();
        } catch (_error) {
          return;
        }
        const zoom = capabilities && capabilities.zoom;
        if (
          !zoom ||
          typeof zoom.min !== 'number' ||
          typeof zoom.max !== 'number'
        ) {
          return;
        }
        const target = Math.min(Math.max(1, zoom.min), zoom.max);
        const settings =
          typeof track.getSettings === 'function' ? track.getSettings() : {};
        if (settings.zoom === target) {
          return;
        }
        try {
          await track.applyConstraints({ advanced: [{ zoom: target }] });
        } catch (error) {
          console.warn(
            'receipt QR scan: failed to apply zoom constraint',
            error,
          );
        }
      },

      async focusAt(x, y) {
        const track = this.stream && this.stream.getVideoTracks()[0];
        const video = this.$refs.video;
        if (!track || !video || typeof track.getCapabilities !== 'function') {
          return;
        }
        let capabilities;
        try {
          capabilities = track.getCapabilities();
        } catch (_error) {
          return;
        }
        if (!capabilities || !capabilities.pointsOfInterest) {
          return;
        }
        const rect = video.getBoundingClientRect();
        const pointX = Math.min(1, Math.max(0, (x - rect.left) / rect.width));
        const pointY = Math.min(1, Math.max(0, (y - rect.top) / rect.height));
        const advanced = { pointsOfInterest: [{ x: pointX, y: pointY }] };
        if (
          capabilities.focusMode &&
          capabilities.focusMode.includes('single-shot')
        ) {
          advanced.focusMode = 'single-shot';
        }
        try {
          await track.applyConstraints({ advanced: [advanced] });
        } catch (error) {
          console.warn('receipt QR scan: failed to focus at point', error);
        }
      },

      handleVideoTap(event) {
        const point =
          event.touches && event.touches.length ? event.touches[0] : event;
        this.focusAt(point.clientX, point.clientY);
      },

      scanFrame() {
        const video = this.$refs.video;
        const canvas = this.$refs.canvas;
        if (!video || !canvas || video.readyState !== video.HAVE_ENOUGH_DATA) {
          return;
        }
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const context = canvas.getContext('2d');
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        const imageData = context.getImageData(
          0,
          0,
          canvas.width,
          canvas.height,
        );
        const decoded = jsQR(imageData.data, imageData.width, imageData.height);
        if (decoded && decoded.data) {
          this.submitDecoded(decoded.data);
        }
      },

      submitDecoded(rawValue) {
        this.stop();
        const form = this.$refs.scanForm;
        const qrInput = form ? form.querySelector('[name="qr_raw"]') : null;
        if (qrInput) {
          qrInput.value = rawValue;
        }
        if (form) {
          form.submit();
        }
      },

      stop() {
        if (this.scanTimer) {
          window.clearInterval(this.scanTimer);
          this.scanTimer = null;
        }
        if (this.stream) {
          this.stream.getTracks().forEach((track) => track.stop());
          this.stream = null;
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
