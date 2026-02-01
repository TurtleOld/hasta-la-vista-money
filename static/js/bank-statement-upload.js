/**
 * Bank Statement Upload - Progress tracking and form handling
 */
(function() {
    'use strict';

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

        /**
         * Update progress UI based on upload status
         */
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
            } else if (data.status === 'completed') {
                progressBar.classList.remove('bg-blue-600', 'dark:bg-blue-500');
                progressBar.classList.add('bg-green-600', 'dark:bg-green-500');
                progressPercent.classList.remove('text-blue-600', 'dark:text-blue-400');
                progressPercent.classList.add('text-green-600', 'dark:text-green-400');
                progressStatus.textContent = `${window.bankStatementTranslations.completed} ${data.income_count} ${window.bankStatementTranslations.incomes}, ${data.expense_count} ${window.bankStatementTranslations.expenses}`;
                progressTitle.innerHTML = `<i class="bi bi-check-circle mr-2"></i>${window.bankStatementTranslations.done}`;

                if (pollInterval) {
                    clearInterval(pollInterval);
                }

                // Redirect after 3 seconds
                setTimeout(function() {
                    window.location.href = window.bankStatementUrls.accountList;
                }, 3000);
            } else if (data.status === 'failed') {
                progressBar.classList.remove('bg-blue-600', 'dark:bg-blue-500');
                progressBar.classList.add('bg-red-600', 'dark:bg-red-500');
                progressPercent.classList.remove('text-blue-600', 'dark:text-blue-400');
                progressPercent.classList.add('text-red-600', 'dark:text-red-400');
                progressStatus.textContent = `${window.bankStatementTranslations.error} ${data.error_message || window.bankStatementTranslations.unknownError}`;
                progressTitle.innerHTML = `<i class="bi bi-exclamation-triangle mr-2"></i>${window.bankStatementTranslations.processingError}`;

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

        // Handle form submission
        if (form) {
            form.addEventListener('submit', function(e) {
                // Disable submit button
                submitBtn.disabled = true;

                // Change button text and icon
                btnText.textContent = window.bankStatementTranslations.uploading;
                uploadIcon.className = 'bi bi-hourglass-split animate-spin';
            });
        }
    });
})();
