(function() {
    'use strict';

    function setupModals() {
        document.querySelectorAll('.modal-open').forEach(button => {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                const modalId = this.getAttribute('data-modal');
                const modal = document.getElementById(modalId);
                if (modal) {
                    document.querySelectorAll('[id^="payment"], [id^="loan"], #payment-options').forEach(m => {
                        m.classList.add('hidden');
                        m.classList.remove('flex');
                    });
                    modal.classList.remove('hidden');
                    modal.classList.add('flex');
                    document.body.style.overflow = 'hidden';

                    if (modalId === 'payment-options') {
                        function processMathJax() {
                            if (typeof window.MathJax !== 'undefined' && window.MathJax.typesetPromise) {
                                if (window.MathJax.typesetClear) {
                                    window.MathJax.typesetClear([modal]);
                                }
                                window.MathJax.typesetPromise([modal]).catch(function(err) {
                                    console.error('MathJax typeset error:', err);
                                });
                            } else if (typeof window.renderMathJax === 'function') {
                                window.renderMathJax(modal);
                            }
                        }

                        requestAnimationFrame(function() {
                            requestAnimationFrame(function() {
                                setTimeout(processMathJax, 100);
                            });
                        });
                    }
                }
            });
        });

        document.querySelectorAll('.modal-close').forEach(button => {
            button.addEventListener('click', function() {
                const modal = this.closest('[id^="payment"], [id^="loan"]') || document.getElementById('payment-options');
                if (modal) {
                    modal.classList.add('hidden');
                    modal.classList.remove('flex');
                    document.body.style.overflow = '';
                }
            });
        });

        document.querySelectorAll('[id^="payment"], [id^="loan"], #payment-options').forEach(modal => {
            modal.addEventListener('click', function(e) {
                if (e.target === this) {
                    this.classList.add('hidden');
                    this.classList.remove('flex');
                    document.body.style.overflow = '';
                }
            });
        });

        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                document.querySelectorAll('[id^="payment"], [id^="loan"], #payment-options').forEach(modal => {
                    if (!modal.classList.contains('hidden')) {
                        modal.classList.add('hidden');
                        modal.classList.remove('flex');
                        document.body.style.overflow = '';
                    }
                });
            }
        });
    }

    function setupFormValidation() {
        const form = document.querySelector('.needs-validation');
        if (form) {
            form.addEventListener('submit', function(event) {
                if (!form.checkValidity()) {
                    event.preventDefault();
                    event.stopPropagation();
                }
                form.classList.add('was-validated');
            });
        }
    }

    function setupCalculationPreview() {
        const loanAmountId = 'id_loan_amount';
        const interestRateId = 'id_annual_interest_rate';
        const periodId = 'id_period_loan';

        const loanAmount = document.getElementById(loanAmountId);
        const interestRate = document.getElementById(interestRateId);
        const period = document.getElementById(periodId);
        const previewElement = document.getElementById('calculation-preview');

        if (!loanAmount || !interestRate || !period || !previewElement) {
            return;
        }

        function updatePreview() {
            if (loanAmount.value && interestRate.value && period.value) {
                const amount = parseFloat(loanAmount.value);
                const rate = parseFloat(interestRate.value) / 100 / 12;
                const months = parseInt(period.value);

                if (rate > 0 && months > 0 && amount > 0) {
                    const monthlyPayment = amount * (rate * Math.pow(1 + rate, months)) / (Math.pow(1 + rate, months) - 1);
                    const totalPayment = monthlyPayment * months;
                    const totalInterest = totalPayment - amount;

                    previewElement.classList.remove('hidden');
                    previewElement.innerHTML = `
                        <div class="flex items-center gap-2 mb-2">
                            <svg class="h-5 w-5 text-blue-600 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path>
                            </svg>
                            <strong class="text-blue-900 dark:text-blue-100">Предварительный расчет:</strong>
                        </div>
                        <div class="space-y-1 text-sm text-blue-800 dark:text-blue-200">
                            <div>Ежемесячный платеж: <strong>${Math.round(monthlyPayment)} ₽</strong></div>
                            <div>Общая переплата: <strong>${Math.round(totalInterest)} ₽</strong></div>
                            <div>Общая сумма к возврату: <strong>${Math.round(totalPayment)} ₽</strong></div>
                        </div>
                    `;
                }
            } else if (previewElement) {
                previewElement.classList.add('hidden');
            }
        }

        [loanAmount, interestRate, period].forEach(field => {
            if (field) {
                field.addEventListener('input', updatePreview);
                field.addEventListener('change', updatePreview);
            }
        });
    }

    document.addEventListener('DOMContentLoaded', function() {
        setupModals();
        setupFormValidation();
        setupCalculationPreview();
    });
})();
