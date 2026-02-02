/**
 * Bank Statement Upload - Progress tracking and form handling
 */
(function() {
    'use strict';

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
