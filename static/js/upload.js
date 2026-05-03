(function () {
    function fileLooksLikeImage(file) {
        if (!file) {
            return false;
        }
        if (file.type === 'image/jpeg' || file.type === 'image/png') {
            return true;
        }
        const name = (file.name || '').toLowerCase();
        return name.endsWith('.jpg') || name.endsWith('.jpeg') || name.endsWith('.png');
    }

    function initReceiptImageUpload() {
        const uploadZone = document.getElementById('upload-zone');
        const fileInput = document.getElementById('file-input');
        const submitBtn = document.getElementById('submitBtn');
        const form = document.getElementById('uploadForm');
        const errorBox = document.getElementById('upload-error');
        const fileNameLabel = document.getElementById('selected-file-name');

        if (!uploadZone || !fileInput || !submitBtn || !form) {
            return;
        }

        const maxSize = 5 * 1024 * 1024;

        const dragActiveClasses = [
            'border-blue-400',
            'dark:border-blue-500',
            'bg-blue-50',
            'dark:bg-blue-900/20'
        ];

        const errorClasses = [
            'border-red-400',
            'dark:border-red-500',
            'bg-red-50',
            'dark:bg-red-900/20'
        ];

        function setZoneClasses(state) {
            uploadZone.classList.remove(...dragActiveClasses);
            uploadZone.classList.remove(...errorClasses);
            if (state === 'drag') {
                uploadZone.classList.add(...dragActiveClasses);
            }
            if (state === 'error') {
                uploadZone.classList.add(...errorClasses);
            }
        }

        function setError(message) {
            setZoneClasses('error');
            if (errorBox) {
                errorBox.textContent = message;
                errorBox.classList.remove('hidden');
            }
        }

        function clearError() {
            setZoneClasses(null);
            if (errorBox) {
                errorBox.textContent = '';
                errorBox.classList.add('hidden');
            }
        }

        function applyFile(file) {
            if (!file) {
                submitBtn.disabled = true;
                if (fileNameLabel) {
                    fileNameLabel.textContent = '';
                }
                return;
            }
            if (!fileLooksLikeImage(file)) {
                setError('Поддерживаются только JPG, JPEG или PNG.');
                submitBtn.disabled = true;
                fileInput.value = '';
                return;
            }
            if (file.size > maxSize) {
                setError('Размер файла не должен превышать 5 МБ.');
                submitBtn.disabled = true;
                fileInput.value = '';
                return;
            }
            clearError();
            submitBtn.disabled = false;
            if (fileNameLabel) {
                fileNameLabel.textContent = file.name;
            }
        }

        fileInput.addEventListener('change', function (event) {
            const target = event.target;
            applyFile(target && target.files ? target.files[0] : null);
        });

        ['dragenter', 'dragover'].forEach(function (eventName) {
            uploadZone.addEventListener(eventName, function (event) {
                event.preventDefault();
                event.stopPropagation();
                setZoneClasses('drag');
            });
        });

        ['dragleave', 'drop'].forEach(function (eventName) {
            uploadZone.addEventListener(eventName, function (event) {
                event.preventDefault();
                event.stopPropagation();
                if (eventName === 'dragleave') {
                    setZoneClasses(null);
                }
            });
        });

        uploadZone.addEventListener('drop', function (event) {
            const dt = event.dataTransfer;
            if (!dt || !dt.files || !dt.files.length) {
                return;
            }
            const file = dt.files[0];
            const transfer = new DataTransfer();
            transfer.items.add(file);
            fileInput.files = transfer.files;
            applyFile(file);
        });

        document.addEventListener('paste', function (event) {
            if (!event.clipboardData || !event.clipboardData.files || !event.clipboardData.files.length) {
                return;
            }
            const file = event.clipboardData.files[0];
            if (!fileLooksLikeImage(file)) {
                return;
            }
            const transfer = new DataTransfer();
            transfer.items.add(file);
            fileInput.files = transfer.files;
            applyFile(file);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initReceiptImageUpload);
    } else {
        initReceiptImageUpload();
    }
})();
