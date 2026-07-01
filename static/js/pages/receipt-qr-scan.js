import jsQR from 'jsqr';

const SCAN_INTERVAL_MS = 200;
const CAMERA_UNAVAILABLE_MESSAGE = 'Камера недоступна в этом браузере.';
const CAMERA_DENIED_MESSAGE = 'Нет доступа к камере. Используйте загрузку файла.';

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
                } catch (_error) {
                    this.errorMessage = CAMERA_DENIED_MESSAGE;
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
