(function () {
    function formatSize(bytes) {
        const numBytes = Number(bytes);
        if (!Number.isFinite(numBytes) || numBytes <= 0) {
            return '0 Б';
        }

        const k = 1024;
        const units = ['Б', 'КБ', 'МБ', 'ГБ'];
        const i = Math.min(Math.floor(Math.log(numBytes) / Math.log(k)), units.length - 1);
        const value = Math.round((numBytes / (k ** i)) * 100) / 100;
        const unitIndex = Math.max(0, Math.min(i, units.length - 1));
        let unit = 'Б';
        if (unitIndex >= 0 && unitIndex < units.length && Array.isArray(units)) {
            const unitValue = units[unitIndex];
            if (typeof unitValue === 'string') {
                unit = unitValue;
            }
        }
        return String(value) + ' ' + unit;
    }

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
        const preview = document.getElementById('preview');
        const previewImage = document.getElementById('preview-image');
        const previewFilename = document.getElementById('preview-filename');
        const previewFilesize = document.getElementById('preview-filesize');
        const removePreview = document.getElementById('remove-preview');
        const submitBtn = document.getElementById('submitBtn');
        const form = document.getElementById('uploadForm');
        const loadingIcon = document.getElementById('loadingIcon');
        const errorBox = document.getElementById('upload-error');

        if (!uploadZone || !fileInput || !submitBtn || !form) {
            return;
        }

        const maxSize = 5 * 1024 * 1024;
        let objectUrl = null;

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

        function setLoading(isLoading) {
            if (!loadingIcon) {
                return;
            }
            if (isLoading) {
                loadingIcon.classList.remove('hidden');
            } else {
                loadingIcon.classList.add('hidden');
            }
        }

        function revokeObjectUrl() {
            if (objectUrl) {
                URL.revokeObjectURL(objectUrl);
                objectUrl = null;
            }
        }

        function setPreview(file) {
            if (!preview || !previewImage) {
                return;
            }

            revokeObjectUrl();
            objectUrl = URL.createObjectURL(file);
            previewImage.src = objectUrl;
            preview.classList.remove('hidden');

            if (previewFilename) {
                previewFilename.textContent = file.name || '';
            }
            if (previewFilesize) {
                previewFilesize.textContent = formatSize(file.size);
            }
        }

        function resetPreview() {
            revokeObjectUrl();

            if (preview) {
                preview.classList.add('hidden');
            }
            if (previewImage) {
                previewImage.removeAttribute('src');
            }
            if (previewFilename) {
                previewFilename.textContent = '';
            }
            if (previewFilesize) {
                previewFilesize.textContent = '';
            }

            fileInput.value = '';
            submitBtn.disabled = true;
            setLoading(false);
            clearError();
        }

        function setFile(file) {
            clearError();

            if (!fileLooksLikeImage(file)) {
                resetPreview();
                setError('Разрешены только файлы форматов: JPG, JPEG или PNG');
                return;
            }

            if (file.size > maxSize) {
                resetPreview();
                setError('Размер файла не должен превышать 5 МБ');
                return;
            }

            const dt = new DataTransfer();
            dt.items.add(file);
            fileInput.files = dt.files;

            setPreview(file);
            submitBtn.disabled = false;
            setZoneClasses(null);
        }

        uploadZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            setZoneClasses('drag');
        });

        uploadZone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            setZoneClasses(null);
        });

        uploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            setZoneClasses(null);
            const files = e.dataTransfer && e.dataTransfer.files ? Array.from(e.dataTransfer.files) : [];
            if (files.length > 0) {
                setFile(files[0]);
            }
        });

        fileInput.addEventListener('change', (e) => {
            const files = e.target && e.target.files ? Array.from(e.target.files) : [];
            if (files.length > 0) {
                setFile(files[0]);
            } else {
                resetPreview();
            }
        });

        document.addEventListener('paste', (e) => {
            const items = e.clipboardData && e.clipboardData.items ? Array.from(e.clipboardData.items) : [];
            for (const item of items) {
                if (item && item.type && item.type.indexOf('image') !== -1) {
                    const file = item.getAsFile();
                    if (file) {
                        setFile(file);
                    }
                    break;
                }
            }
        });

        if (removePreview) {
            removePreview.addEventListener('click', () => {
                resetPreview();
            });
        }

        form.addEventListener('submit', (e) => {
            if (!fileInput.files || fileInput.files.length === 0) {
                e.preventDefault();
                setError('Пожалуйста, выберите изображение для загрузки');
                return;
            }
            submitBtn.disabled = true;
            setLoading(true);
        });
    }

    if (typeof document !== 'undefined') {
        document.addEventListener('DOMContentLoaded', initReceiptImageUpload);
    }
})();
