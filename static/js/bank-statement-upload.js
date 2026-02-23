/**
 * Bank Statement Upload - Drag-and-drop, progress tracking and form handling
 */
(function() {
    'use strict';

    function formatSize(bytes) {
        const numBytes = Number(bytes);
        if (!Number.isFinite(numBytes) || numBytes <= 0) return '0 Б';
        const k = 1024;
        const units = Object.freeze(['Б', 'КБ', 'МБ', 'ГБ']);
        const i = Math.min(Math.floor(Math.log(numBytes) / Math.log(k)), units.length - 1);
        const value = Math.round((numBytes / (k ** i)) * 100) / 100;
        const unit = units[Math.max(0, i)] || 'Б';
        return String(value) + ' ' + unit;
    }

    function initDragAndDrop() {
        const uploadZone = document.getElementById('upload-zone');
        const fileInput = document.getElementById('pdf-file-input');
        const preview = document.getElementById('pdf-preview');
        const filenameEl = document.getElementById('pdf-filename');
        const filesizeEl = document.getElementById('pdf-filesize');
        const removePdf = document.getElementById('remove-pdf');
        const errorBox = document.getElementById('upload-error');
        const submitBtn = document.getElementById('submitBtn');
        const form = document.getElementById('uploadForm');

        if (!uploadZone || !fileInput || !submitBtn || !form) return;

        const maxSize = 10 * 1024 * 1024;

        const dragActiveClasses = [
            'border-blue-400', 'dark:border-blue-500',
            'bg-blue-50', 'dark:bg-blue-900/20'
        ];
        const errorClasses = [
            'border-red-400', 'dark:border-red-500',
            'bg-red-50', 'dark:bg-red-900/20'
        ];

        function setZoneClasses(state) {
            uploadZone.classList.remove(...dragActiveClasses, ...errorClasses);
            if (state === 'drag') uploadZone.classList.add(...dragActiveClasses);
            if (state === 'error') uploadZone.classList.add(...errorClasses);
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

        function showPreview(file) {
            if (filenameEl) filenameEl.textContent = file.name || '';
            if (filesizeEl) filesizeEl.textContent = formatSize(file.size);
            if (preview) preview.classList.remove('hidden');
        }

        function resetFile() {
            fileInput.value = '';
            if (preview) preview.classList.add('hidden');
            if (filenameEl) filenameEl.textContent = '';
            if (filesizeEl) filesizeEl.textContent = '';
            submitBtn.disabled = true;
            clearError();
        }

        function fileLooksPdf(file) {
            if (!file) return false;
            if (file.type === 'application/pdf') return true;
            return (file.name || '').toLowerCase().endsWith('.pdf');
        }

        function setFile(file) {
            clearError();
            if (!fileLooksPdf(file)) {
                resetFile();
                setError('Разрешены только файлы в формате PDF');
                return;
            }
            if (file.size > maxSize) {
                resetFile();
                setError('Размер файла не должен превышать 10 МБ');
                return;
            }
            const dt = new DataTransfer();
            dt.items.add(file);
            fileInput.files = dt.files;
            showPreview(file);
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
            if (files.length > 0) setFile(files[0]);
        });

        fileInput.addEventListener('change', (e) => {
            const files = e.target && e.target.files ? Array.from(e.target.files) : [];
            if (files.length > 0) setFile(files[0]);
            else resetFile();
        });

        if (removePdf) {
            removePdf.addEventListener('click', () => resetFile());
        }

        form.addEventListener('submit', (e) => {
            if (!fileInput.files || fileInput.files.length === 0) {
                e.preventDefault();
                setError('Пожалуйста, выберите PDF файл для загрузки');
                return;
            }
        });

        submitBtn.disabled = true;
    }

    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initDragAndDrop);
        } else {
            initDragAndDrop();
        }
    }

    /**
     * Validates if a URL is safe for redirect
     * @param {string} url - The URL to validate
     * @returns {boolean} - True if URL is safe, false otherwise
     */
    function isValidRedirectUrl(url) {
        if (!url || typeof url !== 'string') {
            return false;
        }

        // Allow relative URLs starting with /
        if (url.startsWith('/')) {
            return true;
        }

        // Allow absolute URLs only if they match the current origin
        try {
            const urlObj = new URL(url, window.location.origin);
            return urlObj.origin === window.location.origin;
        } catch (e) {
            return false;
        }
    }

    // Wait for DOM to be ready
    document.addEventListener('DOMContentLoaded', function() {
        const form = document.getElementById('uploadForm');
        const submitBtn = document.getElementById('submitBtn');
        const btnText = document.getElementById('btnText');
        const uploadIcon = document.getElementById('uploadIcon');
        const progressIndicator = document.getElementById('progressIndicator');
        const progressBar = document.getElementById('progressBar');
        const progressPercent = document.getElementById('progressPercent');
        const progressTitle = document.getElementById('progressTitle');
        const progressStatus = document.getElementById('progressStatus');
        const progressTransactions = document.getElementById('progressTransactions');
        const processedCount = document.getElementById('processedCount');
        const totalCount = document.getElementById('totalCount');

        let pollInterval = null;
        let uploadId = null;

        function updateProgress(data) {
            const progress = data.progress || 0;
            progressBar.style.width = progress + '%';
            progressPercent.textContent = progress + '%';

            if (data.status === 'pending') {
                progressStatus.textContent = window.bankStatementTranslations.pending;
                // Clear and safely set title using DOM methods
                while (progressTitle.firstChild) {
                    progressTitle.removeChild(progressTitle.firstChild);
                }
                progressTitle.appendChild(document.createTextNode(window.bankStatementTranslations.fileUploaded));
            } else if (data.status === 'processing') {
                progressStatus.textContent = window.bankStatementTranslations.processing;
                // Clear and safely set title using DOM methods
                while (progressTitle.firstChild) {
                    progressTitle.removeChild(progressTitle.firstChild);
                }
                progressTitle.appendChild(document.createTextNode(window.bankStatementTranslations.processingStatement));

                if (data.total_transactions > 0) {
                    progressTransactions.classList.remove('hidden');
                    processedCount.textContent = data.processed_transactions;
                    totalCount.textContent = data.total_transactions;
                }
            } else if (data.status === 'completed') {
                progressBar.classList.remove('bg-blue-600', 'dark:bg-blue-500');
                progressBar.classList.add('bg-green-600', 'dark:bg-green-500');
                progressPercent.classList.remove('text-blue-600', 'dark:text-blue-400');
                progressPercent.classList.add('text-green-600', 'dark:text-green-400');
                progressStatus.textContent = `${window.bankStatementTranslations.completed} ${data.income_count} ${window.bankStatementTranslations.incomes}, ${data.expense_count} ${window.bankStatementTranslations.expenses}`;

                // Safely create icon and text elements using DOM methods
                while (progressTitle.firstChild) {
                    progressTitle.removeChild(progressTitle.firstChild);
                }
                const checkIcon = document.createElement('i');
                checkIcon.className = 'bi bi-check-circle mr-2';
                progressTitle.appendChild(checkIcon);
                const doneText = document.createTextNode(window.bankStatementTranslations.done);
                progressTitle.appendChild(doneText);

                if (pollInterval) {
                    clearInterval(pollInterval);
                }

                setTimeout(function() {
                    const redirectUrl = window.bankStatementUrls.accountList;
                    if (redirectUrl) {
                        // Validate URL is safe before navigation
                        if (isValidRedirectUrl(redirectUrl)) {
                            window.location.assign(redirectUrl);
                        }
                    }
                }, 3000);
            } else if (data.status === 'failed') {
                progressBar.classList.remove('bg-blue-600', 'dark:bg-blue-500');
                progressBar.classList.add('bg-red-600', 'dark:bg-red-500');
                progressPercent.classList.remove('text-blue-600', 'dark:text-blue-400');
                progressPercent.classList.add('text-red-600', 'dark:text-red-400');
                progressStatus.textContent = `${window.bankStatementTranslations.error} ${data.error_message || window.bankStatementTranslations.unknownError}`;

                // Safely create icon and text elements using DOM methods
                while (progressTitle.firstChild) {
                    progressTitle.removeChild(progressTitle.firstChild);
                }
                const warningIcon = document.createElement('i');
                warningIcon.className = 'bi bi-exclamation-triangle mr-2';
                progressTitle.appendChild(warningIcon);
                const errorText = document.createTextNode(window.bankStatementTranslations.processingError);
                progressTitle.appendChild(errorText);

                if (pollInterval) {
                    clearInterval(pollInterval);
                }
            }
        }

        /**
         * Poll upload status from server
         */
        function pollUploadStatus() {
            if (!uploadId) return;

            // Validate uploadId is numeric to prevent injection
            if (!/^\d+$/.test(uploadId)) {
                console.error('Invalid upload ID format');
                return;
            }

            const statusUrl = window.bankStatementUrls.statusUrl.replace('0', uploadId);
            fetch(statusUrl)
                .then(response => response.json())
                .then(data => {
                    updateProgress(data);
                })
                .catch(error => {
                    console.error('Error polling status:', error);
                });
        }

        // Check for ongoing upload from context or session
        const contextUploadId = window.bankStatementData?.uploadId || '';
        const showProgress = window.bankStatementData?.showProgress || false;
        const lastUploadId = contextUploadId || window.bankStatementData?.sessionUploadId || '';

        console.log('Debug: contextUploadId=', contextUploadId);
        console.log('Debug: showProgress=', showProgress);
        console.log('Debug: lastUploadId=', lastUploadId);

        if (showProgress && lastUploadId) {
            uploadId = lastUploadId;
            console.log('Showing progress bar for upload:', uploadId);
            progressIndicator.classList.remove('hidden');
            progressIndicator.scrollIntoView({ behavior: 'smooth', block: 'center' });
            pollInterval = setInterval(pollUploadStatus, 2000);
            pollUploadStatus(); // Initial call
        } else {
            console.log('Not showing progress bar. showProgress=', showProgress, 'lastUploadId=', lastUploadId);
        }

        if (form) {
            form.addEventListener('submit', function() {
                submitBtn.disabled = true;

                btnText.textContent = window.bankStatementTranslations.uploading;
                uploadIcon.className = 'bi bi-hourglass-split animate-spin';
            });
        }
    });
})();
