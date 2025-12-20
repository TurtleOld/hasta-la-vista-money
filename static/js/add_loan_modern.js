(function() {
    'use strict';

    function setupModals() {
        function processMathJax(modal) {
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
                        requestAnimationFrame(function() {
                            requestAnimationFrame(function() {
                                setTimeout(function() {
                                    processMathJax(modal);
                                }, 100);
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
                    previewElement.textContent = '';

                    const headerDiv = document.createElement('div');
                    headerDiv.className = 'flex items-center gap-2 mb-2';

                    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                    svg.setAttribute('class', 'h-5 w-5 text-blue-600 dark:text-blue-400');
                    svg.setAttribute('fill', 'none');
                    svg.setAttribute('stroke', 'currentColor');
                    svg.setAttribute('viewBox', '0 0 24 24');
                    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                    path.setAttribute('stroke-linecap', 'round');
                    path.setAttribute('stroke-linejoin', 'round');
                    path.setAttribute('stroke-width', '2');
                    path.setAttribute('d', 'M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z');
                    svg.appendChild(path);

                    const strong = document.createElement('strong');
                    strong.className = 'text-blue-900 dark:text-blue-100';
                    strong.textContent = 'Предварительный расчет:';

                    headerDiv.appendChild(svg);
                    headerDiv.appendChild(strong);

                    const contentDiv = document.createElement('div');
                    contentDiv.className = 'space-y-1 text-sm text-blue-800 dark:text-blue-200';

                    const monthlyDiv = document.createElement('div');
                    monthlyDiv.appendChild(document.createTextNode('Ежемесячный платеж: '));
                    const monthlyStrong = document.createElement('strong');
                    monthlyStrong.appendChild(document.createTextNode(String(Math.round(monthlyPayment)) + ' ₽'));
                    monthlyDiv.appendChild(monthlyStrong);

                    const interestDiv = document.createElement('div');
                    interestDiv.appendChild(document.createTextNode('Общая переплата: '));
                    const interestStrong = document.createElement('strong');
                    interestStrong.appendChild(document.createTextNode(String(Math.round(totalInterest)) + ' ₽'));
                    interestDiv.appendChild(interestStrong);

                    const totalDiv = document.createElement('div');
                    totalDiv.appendChild(document.createTextNode('Общая сумма к возврату: '));
                    const totalStrong = document.createElement('strong');
                    totalStrong.appendChild(document.createTextNode(String(Math.round(totalPayment)) + ' ₽'));
                    totalDiv.appendChild(totalStrong);

                    contentDiv.appendChild(monthlyDiv);
                    contentDiv.appendChild(interestDiv);
                    contentDiv.appendChild(totalDiv);

                    previewElement.appendChild(headerDiv);
                    previewElement.appendChild(contentDiv);
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
