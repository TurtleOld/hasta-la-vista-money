function registerReceiptUploadPage(Alpine) {
    Alpine.data('receiptUploadPage', function () {
        return {
            files: [],
            errorMessage: '',
            isDragging: false,
            maxSize: 5 * 1024 * 1024,

            get hasFiles() {
                return this.files.length > 0;
            },

            get selectedFileLabel() {
                if (this.files.length === 0) {
                    return '';
                }
                if (this.files.length === 1) {
                    return this.files[0].name;
                }
                return 'Выбрано файлов: ' + this.files.length;
            },

            get zoneClass() {
                if (this.errorMessage) {
                    return 'border-red-400 dark:border-red-500 bg-red-50 dark:bg-red-900/20';
                }
                if (this.isDragging) {
                    return 'border-blue-400 dark:border-blue-500 bg-blue-50 dark:bg-blue-900/20';
                }
                return '';
            },

            init() {
                document.addEventListener('paste', this.handlePaste.bind(this));
            },

            handleInputChange(event) {
                this.applyFiles(event.target.files || []);
            },

            handleDragEnter(event) {
                event.preventDefault();
                this.isDragging = true;
            },

            handleDragOver(event) {
                event.preventDefault();
                this.isDragging = true;
            },

            handleDragLeave(event) {
                event.preventDefault();
                this.isDragging = false;
            },

            handleDrop(event) {
                event.preventDefault();
                this.isDragging = false;
                if (!event.dataTransfer || !event.dataTransfer.files.length) {
                    return;
                }
                this.setInputFiles(event.dataTransfer.files);
                this.applyFiles(event.dataTransfer.files);
            },

            handlePaste(event) {
                if (!event.clipboardData || !event.clipboardData.files.length) {
                    return;
                }
                const images = Array.from(event.clipboardData.files).filter(
                    this.fileLooksLikeImage,
                );
                if (!images.length) {
                    return;
                }
                this.setInputFiles(images);
                this.applyFiles(images);
            },

            applyFiles(fileList) {
                this.revokePreviewUrls();
                const selectedFiles = Array.from(fileList || []);
                if (!selectedFiles.length) {
                    this.files = [];
                    this.errorMessage = '';
                    return;
                }

                const invalidFile = selectedFiles.find(
                    file => !this.fileLooksLikeImage(file),
                );
                if (invalidFile) {
                    this.rejectFiles('Поддерживаются только JPG, JPEG или PNG.');
                    return;
                }

                const oversizedFile = selectedFiles.find(
                    file => file.size > this.maxSize,
                );
                if (oversizedFile) {
                    this.rejectFiles('Размер файла не должен превышать 5 МБ.');
                    return;
                }

                this.errorMessage = '';
                this.files = selectedFiles.map(file => ({
                    name: file.name || 'Изображение',
                    previewUrl: URL.createObjectURL(file),
                }));
            },

            setInputFiles(fileList) {
                const input = this.$refs.fileInput;
                if (!input || typeof DataTransfer === 'undefined') {
                    return;
                }
                const transfer = new DataTransfer();
                Array.from(fileList || []).forEach(file => {
                    transfer.items.add(file);
                });
                input.files = transfer.files;
            },

            rejectFiles(message) {
                this.files = [];
                this.errorMessage = message;
                if (this.$refs.fileInput) {
                    this.$refs.fileInput.value = '';
                }
            },

            revokePreviewUrls() {
                this.files.forEach(file => {
                    if (file.previewUrl) {
                        URL.revokeObjectURL(file.previewUrl);
                    }
                });
            },

            fileLooksLikeImage(file) {
                if (!file) {
                    return false;
                }
                if (file.type === 'image/jpeg' || file.type === 'image/png') {
                    return true;
                }
                const name = (file.name || '').toLowerCase();
                return name.endsWith('.jpg') || name.endsWith('.jpeg') || name.endsWith('.png');
            },
        };
    });
}

if (window.Alpine) {
    registerReceiptUploadPage(window.Alpine);
} else {
    document.addEventListener('alpine:init', function () {
        registerReceiptUploadPage(window.Alpine);
    });
}
