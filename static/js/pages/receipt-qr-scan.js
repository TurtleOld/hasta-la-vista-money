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
    if (name === 'OverconstrainedError' || name === 'ConstraintNotSatisfiedError') {
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
                document.addEventListener('receipt-scan:activate', this.start.bind(this));
                document.addEventListener('receipt-scan:deactivate', this.stop.bind(this));
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
                        video: { facingMode: 'environment' },
                    });
                } catch (error) {
                    console.error('receipt QR scan: camera access failed', error);
                    this.errorMessage = describeCameraError(error);
                    return;
                }
                const video = this.$refs.video;
                if (!video) {
                    this.stop();
                    return;
                }
                video.srcObject = this.stream;
                await video.play();
                this.scanTimer = window.setInterval(this.scanFrame.bind(this), SCAN_INTERVAL_MS);
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
                const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
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
                    this.stream.getTracks().forEach(track => track.stop());
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
