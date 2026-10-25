import { icon } from './icons.js';

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

        function setZoneClasses(state) {
            if (state === 'drag' || state === 'error') uploadZone.dataset.state = state;
            else delete uploadZone.dataset.state;
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

    function isValidRedirectUrl(url) {
        if (!url || typeof url !== 'string') {
            return false;
        }

        if (url.startsWith('/')) {
            return true;
        }

        try {
            const urlObj = new URL(url, window.location.origin);
            return urlObj.origin === window.location.origin;
        } catch {
            return false;
        }
    }

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
        const reconciliationBlock = document.getElementById('reconciliationBlock');
        const reconStatementBalance = document.getElementById('reconStatementBalance');
        const reconAppBalance = document.getElementById('reconAppBalance');
        const reconDiscrepancy = document.getElementById('reconDiscrepancy');

        let pollInterval = null;
        let uploadId = null;

        function updateProgress(data) {
            const progress = data.progress || 0;
            progressBar.style.width = progress + '%';
            progressPercent.textContent = progress + '%';

            if (data.status === 'pending') {
                progressStatus.textContent = window.bankStatementTranslations.pending;
                progressTitle.textContent = window.bankStatementTranslations.fileUploaded;
            } else if (data.status === 'processing') {
                progressStatus.textContent = window.bankStatementTranslations.processing;
                progressTitle.textContent = window.bankStatementTranslations.processingStatement;

                if (data.total_transactions > 0) {
                    progressTransactions.classList.remove('hidden');
                    processedCount.textContent = data.processed_transactions;
                    totalCount.textContent = data.total_transactions;
                }
            } else if (data.status === 'awaiting_confirmation') {
                if (pollInterval) {
                    clearInterval(pollInterval);
                }
                if (isValidRedirectUrl(data.reconciliation_url)) {
                    window.location.assign(data.reconciliation_url);
                }
            } else if (data.status === 'completed' || data.status === 'completed_with_unresolved') {
                progressIndicator.dataset.state = 'done';
                let completedText = `${window.bankStatementTranslations.completed} ${data.income_count} ${window.bankStatementTranslations.incomes}, ${data.expense_count} ${window.bankStatementTranslations.expenses}`;
                if (data.skipped_count && data.skipped_count > 0) {
                    completedText += `, ${data.skipped_count} ${window.bankStatementTranslations.skipped}`;
                }
                if (data.needs_transfer_count && data.needs_transfer_count > 0) {
                    completedText += `, ${window.bankStatementTranslations.pendingTransfersPrefix} ${data.needs_transfer_count} ${window.bankStatementTranslations.pendingTransfersSuffix}`;
                }
                progressStatus.textContent = completedText;

                progressTitle.textContent = window.bankStatementTranslations.done;

                if (data.statement_closing_balance !== null && data.statement_closing_balance !== undefined) {
                    if (reconciliationBlock) reconciliationBlock.classList.remove('hidden');
                    if (reconStatementBalance) reconStatementBalance.textContent = data.statement_closing_balance;
                    if (reconAppBalance) reconAppBalance.textContent = data.account_balance_after;

                    const discrepancy = parseFloat(data.balance_discrepancy);
                    if (reconDiscrepancy) {
                        if (discrepancy === 0) {
                            reconDiscrepancy.textContent = window.bankStatementTranslations.balanceMatch;
                            reconDiscrepancy.classList.add('finances-positive');
                        } else {
                            reconDiscrepancy.textContent = data.balance_discrepancy;
                            reconDiscrepancy.classList.add('finances-negative');
                        }
                    }
                }

                if (pollInterval) {
                    clearInterval(pollInterval);
                }

                setTimeout(function() {
                    const redirectUrl = window.bankStatementUrls.accountList;
                    if (redirectUrl) {
                        if (isValidRedirectUrl(redirectUrl)) {
                            window.location.assign(redirectUrl);
                        }
                    }
                }, 5000);
            } else if (data.status === 'failed') {
                progressIndicator.dataset.state = 'failed';
                progressStatus.textContent = `${window.bankStatementTranslations.error} ${data.error_message || window.bankStatementTranslations.unknownError}`;

                progressTitle.textContent = window.bankStatementTranslations.processingError;

                if (pollInterval) {
                    clearInterval(pollInterval);
                }
            }
        }

        function pollUploadStatus() {
            if (!uploadId) return;

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

        const contextUploadId = window.bankStatementData?.uploadId || '';
        const showProgress = window.bankStatementData?.showProgress || false;
        const lastUploadId = contextUploadId || window.bankStatementData?.sessionUploadId || '';

        if (showProgress && lastUploadId) {
            uploadId = lastUploadId;
            progressIndicator.classList.remove('hidden');
            progressIndicator.scrollIntoView({ behavior: 'smooth', block: 'center' });
            pollInterval = setInterval(pollUploadStatus, 2000);
            pollUploadStatus();
        }

        if (form) {
            form.addEventListener('submit', function() {
                submitBtn.disabled = true;

                btnText.textContent = window.bankStatementTranslations.uploading;
                uploadIcon.replaceWith(icon('refresh', 'animate-spin'));
            });
        }
    });
})();
