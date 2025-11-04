class ReceiptUploader {
    constructor(dropZoneId, options = {}) {
        this.dropZone = document.getElementById(dropZoneId);
        if (!this.dropZone) return;

        this.options = {
            maxFiles: 5,
            maxSize: 5 * 1024 * 1024,
            allowedTypes: ['image/jpeg', 'image/jpg', 'image/png'],
            uploadUrl: '/receipts/upload/',
            ...options
        };

        this.files = [];
        this.init();
    }

    init() {
        this.createPreviewContainer();
        this.attachEvents();
    }

    createPreviewContainer() {
        if (!document.getElementById('preview-container')) {
            const container = document.createElement('div');
            container.id = 'preview-container';
            container.className = 'preview-container';
            this.dropZone.parentNode.insertBefore(container, this.dropZone.nextSibling);
        }
    }

    attachEvents() {
        this.dropZone.addEventListener('click', () => {
            const input = document.getElementById('file-input');
            if (input) input.click();
        });

        this.dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            this.dropZone.classList.add('dragover');
        });

        this.dropZone.addEventListener('dragleave', () => {
            this.dropZone.classList.remove('dragover');
        });

        this.dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            this.dropZone.classList.remove('dragover');
            const files = Array.from(e.dataTransfer.files);
            this.handleFiles(files);
        });

        const fileInput = document.getElementById('file-input');
        if (fileInput) {
            fileInput.addEventListener('change', (e) => {
                const files = Array.from(e.target.files);
                this.handleFiles(files);
            });
        }

        document.addEventListener('paste', (e) => {
            const items = e.clipboardData.items;
            for (const item of items) {
                if (item.type.indexOf('image') !== -1) {
                    const file = item.getAsFile();
                    this.handleFiles([file]);
                    break;
                }
            }
        });
    }

    handleFiles(files) {
        for (const file of files) {
            if (this.files.length >= this.options.maxFiles) {
                window.toast.warning(`Максимум ${this.options.maxFiles} файлов за раз`);
                break;
            }

            if (!this.validateFile(file)) {
                continue;
            }

            this.files.push(file);
            this.createPreview(file);
        }
    }

    validateFile(file) {
        if (!this.options.allowedTypes.includes(file.type)) {
            window.toast.error(`Неподдерживаемый формат: ${file.name}`);
            return false;
        }

        if (file.size > this.options.maxSize) {
            window.toast.error(`Файл слишком большой: ${file.name} (максимум ${this.formatSize(this.options.maxSize)})`);
            return false;
        }

        return true;
    }

    createPreview(file) {
        const container = document.getElementById('preview-container');
        const previewId = `preview-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;

        const previewCard = document.createElement('div');
        previewCard.className = 'preview-card';
        previewCard.id = previewId;

        const imageWrapper = document.createElement('div');
        imageWrapper.className = 'preview-image-wrapper';

        const img = document.createElement('img');
        img.className = 'preview-image';
        img.setAttribute('alt', file.name || '');

        imageWrapper.appendChild(img);

        const previewInfo = document.createElement('div');
        previewInfo.className = 'preview-info';

        const filenameDiv = document.createElement('div');
        filenameDiv.className = 'preview-filename';
        filenameDiv.textContent = file.name || '';

        const sizeDiv = document.createElement('div');
        sizeDiv.className = 'preview-size';
        sizeDiv.textContent = this.formatSize(file.size);

        const previewProgress = document.createElement('div');
        previewProgress.className = 'preview-progress';

        const progress = document.createElement('div');
        progress.className = 'progress';

        const progressBar = document.createElement('div');
        progressBar.className = 'progress-bar';
        progressBar.setAttribute('role', 'progressbar');
        progressBar.style.width = '0%';

        progress.appendChild(progressBar);

        const statusDiv = document.createElement('div');
        statusDiv.className = 'preview-status';
        statusDiv.textContent = 'Ожидание...';

        previewProgress.appendChild(progress);
        previewProgress.appendChild(statusDiv);

        previewInfo.appendChild(filenameDiv);
        previewInfo.appendChild(sizeDiv);
        previewInfo.appendChild(previewProgress);

        const removeBtn = document.createElement('button');
        removeBtn.className = 'preview-remove';
        removeBtn.setAttribute('type', 'button');
        removeBtn.setAttribute('aria-label', 'Удалить');

        const closeIcon = document.createElement('i');
        closeIcon.className = 'bi bi-x';
        removeBtn.appendChild(closeIcon);

        previewCard.appendChild(imageWrapper);
        previewCard.appendChild(previewInfo);
        previewCard.appendChild(removeBtn);

        container.appendChild(previewCard);

        const reader = new FileReader();
        reader.onload = (e) => {
            img.src = e.target.result;
        };
        reader.readAsDataURL(file);

        removeBtn.addEventListener('click', () => {
            this.removeFile(file, previewId);
        });
    }

    removeFile(file, previewId) {
        const index = this.files.indexOf(file);
        if (index > -1) {
            this.files.splice(index, 1);
        }

        const previewCard = document.getElementById(previewId);
        if (previewCard) {
            previewCard.remove();
        }
    }

    uploadFile(file, previewId) {
        const formData = new FormData();
        formData.append('file', file);

        const csrfToken = this.getCookie('csrftoken');
        if (csrfToken) {
            formData.append('csrfmiddlewaretoken', csrfToken);
        }

        const xhr = new XMLHttpRequest();

        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const percent = Math.round((e.loaded / e.total) * 100);
                this.updateProgress(previewId, percent);
            }
        });

        xhr.addEventListener('load', () => {
            if (xhr.status === 200) {
                try {
                    const response = JSON.parse(xhr.responseText);
                    if (response.success) {
                        this.updateStatus(previewId, 'Загружено', 'success');
                        window.toast.success(`Файл ${file.name} успешно загружен`);
                        setTimeout(() => {
                            this.removeFile(file, previewId);
                        }, 2000);
                    } else {
                        this.updateStatus(previewId, 'Ошибка', 'error');
                        window.toast.error(response.error || 'Ошибка загрузки');
                    }
                } catch {
                    this.updateStatus(previewId, 'Ошибка', 'error');
                    window.toast.error('Ошибка обработки ответа');
                }
            } else {
                this.updateStatus(previewId, 'Ошибка', 'error');
                window.toast.error(`Ошибка загрузки: ${xhr.status}`);
            }
        });

        xhr.addEventListener('error', () => {
            this.updateStatus(previewId, 'Ошибка', 'error');
            window.toast.error('Ошибка сети');
        });

        xhr.open('POST', this.options.uploadUrl);
        xhr.send(formData);
    }

    uploadAll() {
        if (this.files.length === 0) {
            window.toast.warning('Выберите файлы для загрузки');
            return;
        }

        this.files.forEach((file, index) => {
            const previewCard = document.querySelectorAll('.preview-card')[index];
            if (previewCard) {
                setTimeout(() => {
                    this.uploadFile(file, previewCard.id);
                }, index * 300);
            }
        });
    }

    updateProgress(previewId, percent) {
        const card = document.getElementById(previewId);
        if (!card) return;

        const progressBar = card.querySelector('.progress-bar');
        const status = card.querySelector('.preview-status');

        if (progressBar) {
            progressBar.style.width = `${percent}%`;
        }

        if (status) {
            status.textContent = `Загрузка... ${percent}%`;
        }
    }

    updateStatus(previewId, message, type) {
        const card = document.getElementById(previewId);
        if (!card) return;

        const status = card.querySelector('.preview-status');
        const progressBar = card.querySelector('.progress-bar');

        if (status) {
            status.textContent = message;
            status.className = `preview-status status-${type}`;
        }

        if (progressBar) {
            progressBar.className = `progress-bar bg-${type === 'success' ? 'success' : 'danger'}`;
            progressBar.style.width = '100%';
        }
    }

    formatSize(bytes) {
        if (bytes === 0) return '0 Б';
        const k = 1024;
        const sizes = ['Б', 'КБ', 'МБ', 'ГБ'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
    }

    getCookie(name) {
        if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
            return null;
        }
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (const cookieRaw of cookies) {
                const cookie = cookieRaw.trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
}

if (typeof window !== 'undefined') {
    window.ReceiptUploader = ReceiptUploader;
}
