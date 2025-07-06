/**
 * Loan Module JavaScript
 * Обеспечивает интерактивность для кредитного модуля
 */

class LoanManager {
    constructor() {
        this.initializeEventListeners();
        this.initializeTooltips();
        this.initializeCharts();
    }

    /**
     * Инициализация обработчиков событий
     */
    initializeEventListeners() {
        // Форма добавления кредита
        this.setupLoanForm();

        // Модальные окна
        this.setupModals();

        // Фильтры и поиск
        this.setupFilters();

        // Экспорт данных
        this.setupExport();
    }

    /**
     * Настройка формы кредита
     */
    setupLoanForm() {
        const form = document.querySelector('.needs-validation');
        if (form) {
            // Валидация формы
            form.addEventListener('submit', (event) => {
                if (!form.checkValidity()) {
                    event.preventDefault();
                    event.stopPropagation();
                }
                form.classList.add('was-validated');
            });

            // Предварительный расчет
            this.setupCalculationPreview();
        }
    }

    /**
     * Настройка предварительного расчета
     */
    setupCalculationPreview() {
        const loanAmount = document.getElementById('id_loan_amount');
        const interestRate = document.getElementById('id_annual_interest_rate');
        const period = document.getElementById('id_period_loan');
        const typeLoan = document.getElementById('id_type_loan');

        if (loanAmount && interestRate && period) {
            const updatePreview = () => {
                if (loanAmount.value && interestRate.value && period.value) {
                    const amount = parseFloat(loanAmount.value);
                    const rate = parseFloat(interestRate.value) / 100 / 12;
                    const months = parseInt(period.value);
                    const type = typeLoan ? typeLoan.value : 'Annuity';

                    if (rate > 0 && months > 0) {
                        const result = this.calculateLoan(amount, rate, months, type);
                        this.showCalculationPreview(result);
                    }
                }
            };

            [loanAmount, interestRate, period, typeLoan].forEach(field => {
                if (field) {
                    field.addEventListener('input', updatePreview);
                    field.addEventListener('change', updatePreview);
                }
            });
        }
    }

    /**
     * Расчет кредита
     */
    calculateLoan(amount, monthlyRate, months, type) {
        if (type === 'Annuity') {
            // Аннуитетный платеж
            const monthlyPaymentRaw = amount * (monthlyRate * Math.pow(1 + monthlyRate, months)) /
                                 (Math.pow(1 + monthlyRate, months) - 1);
            let totalPayment = 0;
            for (let i = 0; i < months; i++) {
                totalPayment += Math.round(monthlyPaymentRaw * 100) / 100;
            }
            const totalInterest = totalPayment - amount;

            return {
                monthlyPayment: Math.round(monthlyPaymentRaw * 100) / 100,
                totalPayment: totalPayment,
                totalInterest: totalInterest,
                type: 'annuity'
            };
        } else {
            // Дифференцированный платеж
            const principalPayment = amount / months;
            let totalInterest = 0;
            let totalPayment = 0;
            let remainingBalance = amount;
            for (let i = 0; i < months; i++) {
                const interestPayment = remainingBalance * monthlyRate;
                const monthlyPayment = principalPayment + interestPayment;
                totalInterest += interestPayment;
                totalPayment += Math.round(monthlyPayment * 100) / 100;
                remainingBalance -= principalPayment;
            }
            return {
                firstPayment: Math.round((principalPayment + (amount * monthlyRate)) * 100) / 100,
                lastPayment: Math.round((principalPayment + (principalPayment * monthlyRate)) * 100) / 100,
                totalPayment: totalPayment,
                totalInterest: Math.round(totalInterest * 100) / 100,
                type: 'differentiated'
            };
        }
    }

    /**
     * Показать предварительный расчет
     */
    showCalculationPreview(result) {
        let previewElement = document.getElementById('calculation-preview');

        if (!previewElement) {
            previewElement = document.createElement('div');
            previewElement.id = 'calculation-preview';
            const form = document.querySelector('.needs-validation');
            if (form) {
                form.insertBefore(previewElement, form.querySelector('.form-actions'));
            }
        }

        previewElement.innerHTML = '';

        const alertDiv = document.createElement('div');
        alertDiv.className = 'alert alert-info mt-3';

        const header = document.createElement('h6');
        const icon = document.createElement('i');
        icon.className = 'bi bi-calculator me-2';
        header.appendChild(icon);
        header.appendChild(document.createTextNode('Предварительный расчет'));
        alertDiv.appendChild(header);

        if (result.type === 'annuity') {
            const monthlyPaymentP = document.createElement('p');
            const monthlyPaymentStrong = document.createElement('strong');
            monthlyPaymentStrong.textContent = 'Ежемесячный платеж: ';
            monthlyPaymentP.appendChild(monthlyPaymentStrong);
            monthlyPaymentP.appendChild(document.createTextNode(`${result.monthlyPayment.toFixed(2)} ₽`));
            alertDiv.appendChild(monthlyPaymentP);
        } else {
            const firstPaymentP = document.createElement('p');
            const firstPaymentStrong = document.createElement('strong');
            firstPaymentStrong.textContent = 'Первый платеж: ';
            firstPaymentP.appendChild(firstPaymentStrong);
            firstPaymentP.appendChild(document.createTextNode(`${result.firstPayment.toFixed(2)} ₽`));
            alertDiv.appendChild(firstPaymentP);

            const lastPaymentP = document.createElement('p');
            const lastPaymentStrong = document.createElement('strong');
            lastPaymentStrong.textContent = 'Последний платеж: ';
            lastPaymentP.appendChild(lastPaymentStrong);
            lastPaymentP.appendChild(document.createTextNode(`${result.lastPayment.toFixed(2)} ₽`));
            alertDiv.appendChild(lastPaymentP);
        }

        const totalInterestP = document.createElement('p');
        const totalInterestStrong = document.createElement('strong');
        totalInterestStrong.textContent = 'Общая переплата: ';
        totalInterestP.appendChild(totalInterestStrong);
        totalInterestP.appendChild(document.createTextNode(`${result.totalInterest.toFixed(2)} ₽`));
        alertDiv.appendChild(totalInterestP);

        const totalPaymentP = document.createElement('p');
        const totalPaymentStrong = document.createElement('strong');
        totalPaymentStrong.textContent = 'Общая сумма к возврату: ';
        totalPaymentP.appendChild(totalPaymentStrong);
        totalPaymentP.appendChild(document.createTextNode(`${result.totalPayment.toFixed(2)} ₽`));
        alertDiv.appendChild(totalPaymentP);

        previewElement.appendChild(alertDiv);
    }

    /**
     * Настройка модальных окон
     */
    setupModals() {
        // Улучшенные модальные окна
        document.querySelectorAll('[data-bs-toggle="modal"]').forEach(button => {
            button.addEventListener('click', (e) => {
                const target = button.getAttribute('data-bs-target');
                const modal = document.querySelector(target);

                if (modal) {
                    // Добавить анимацию загрузки
                    const modalBody = modal.querySelector('.modal-body');
                    if (modalBody && !modalBody.querySelector('.loan-loading')) {
                        const loadingDiv = document.createElement('div');
                        loadingDiv.className = 'loan-loading';

                        const spinner = document.createElement('div');
                        spinner.className = 'spinner-border';

                        loadingDiv.appendChild(spinner);
                        loadingDiv.appendChild(document.createTextNode('Загрузка...'));

                        modalBody.insertBefore(loadingDiv, modalBody.firstChild);
                    }
                }
            });
        });

        // Обработка закрытия модальных окон
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('hidden.bs.modal', () => {
                // Очистить загрузочные состояния
                const loadingElements = modal.querySelectorAll('.loan-loading');
                loadingElements.forEach(el => el.remove());
            });
        });
    }

    /**
     * Настройка фильтров
     */
    setupFilters() {
        // Фильтр по статусу
        const statusFilter = document.getElementById('status-filter');
        if (statusFilter) {
            statusFilter.addEventListener('change', (e) => {
                this.filterLoans('status', e.target.value);
            });
        }

        // Поиск по номеру кредита
        const searchInput = document.getElementById('loan-search');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this.filterLoans('search', e.target.value);
            });
        }

        // Сортировка
        const sortSelect = document.getElementById('sort-loans');
        if (sortSelect) {
            sortSelect.addEventListener('change', (e) => {
                this.sortLoans(e.target.value);
            });
        }
    }

    /**
     * Фильтрация кредитов
     */
    filterLoans(type, value) {
        const loanCards = document.querySelectorAll('.loan-card');

        loanCards.forEach(card => {
            let show = true;

            if (type === 'status') {
                const status = card.querySelector('.loan-status').textContent;
                show = value === 'all' || status.includes(value);
            } else if (type === 'search') {
                const loanNumber = card.querySelector('.loan-number').textContent;
                show = loanNumber.toLowerCase().includes(value.toLowerCase());
            }

            card.style.display = show ? 'block' : 'none';
        });
    }

    /**
     * Сортировка кредитов
     */
    sortLoans(criteria) {
        const container = document.querySelector('.row');
        const cards = Array.from(container.querySelectorAll('.col-lg-6, .col-xl-4'));

        cards.sort((a, b) => {
            const cardA = a.querySelector('.loan-card');
            const cardB = b.querySelector('.loan-card');

            let valueA, valueB;

            switch (criteria) {
                case 'amount':
                    valueA = parseFloat(cardA.querySelector('.amount .info-value').textContent);
                    valueB = parseFloat(cardB.querySelector('.amount .info-value').textContent);
                    return valueB - valueA; // По убыванию
                case 'rate':
                    valueA = parseFloat(cardA.querySelector('.rate .info-value').textContent);
                    valueB = parseFloat(cardB.querySelector('.rate .info-value').textContent);
                    return valueB - valueA;
                case 'period':
                    valueA = parseInt(cardA.querySelector('.period .info-value').textContent);
                    valueB = parseInt(cardB.querySelector('.period .info-value').textContent);
                    return valueA - valueB; // По возрастанию
                default:
                    return 0;
            }
        });

        // Пересортировать элементы
        cards.forEach(card => container.appendChild(card));
    }

    /**
     * Настройка экспорта
     */
    setupExport() {
        const exportBtn = document.getElementById('export-loans');
        if (exportBtn) {
            exportBtn.addEventListener('click', () => {
                this.exportLoansData();
            });
        }
    }

    /**
     * Экспорт данных кредитов
     */
    exportLoansData() {
        const loans = [];
        document.querySelectorAll('.loan-card').forEach(card => {
            const loan = {
                number: card.querySelector('.loan-number').textContent,
                amount: card.querySelector('.amount .info-value').textContent,
                rate: card.querySelector('.rate .info-value').textContent,
                period: card.querySelector('.period .info-value').textContent,
                totalAmount: card.querySelector('.summary-row:last-child .fw-bold').textContent,
                overpayment: card.querySelector('.summary-row:last-child-1 .fw-bold').textContent
            };
            loans.push(loan);
        });

        // Создать CSV
        const csv = this.convertToCSV(loans);
        this.downloadCSV(csv, 'loans_export.csv');
    }

    /**
     * Конвертация в CSV
     */
    convertToCSV(data) {
        const headers = ['Номер кредита', 'Сумма', 'Ставка', 'Срок', 'Общая сумма', 'Переплата'];
        const rows = data.map(loan => [
            loan.number,
            loan.amount,
            loan.rate,
            loan.period,
            loan.totalAmount,
            loan.overpayment
        ]);

        return [headers, ...rows].map(row =>
            row.map(cell => `"${cell}"`).join(',')
        ).join('\n');
    }

    /**
     * Скачивание CSV файла
     */
    downloadCSV(csv, filename) {
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);
        link.setAttribute('href', url);
        link.setAttribute('download', filename);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    /**
     * Инициализация тултипов
     */
    initializeTooltips() {
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }

    /**
     * Инициализация графиков
     */
    initializeCharts() {
        // График платежей
        this.setupPaymentChart();

        // График прогресса погашения
        this.setupProgressChart();
    }

    /**
     * Настройка графика платежей
     */
    setupPaymentChart() {
        const chartCanvas = document.getElementById('payment-chart');
        if (chartCanvas && typeof Chart !== 'undefined') {
            const ctx = chartCanvas.getContext('2d');

            // Получить данные из таблицы
            const table = document.querySelector('.schedule-table');
            if (table) {
                const rows = table.querySelectorAll('tbody tr');
                const labels = [];
                const payments = [];
                const interests = [];
                const principals = [];

                rows.forEach((row, index) => {
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 4) {
                        labels.push(`Месяц ${index + 1}`);
                        payments.push(parseFloat(cells[2].textContent));
                        interests.push(parseFloat(cells[3].textContent));
                        principals.push(parseFloat(cells[4].textContent));
                    }
                });

                new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Ежемесячный платеж',
                            data: payments,
                            borderColor: '#198754',
                            backgroundColor: 'rgba(25, 135, 84, 0.1)',
                            tension: 0.1
                        }, {
                            label: 'Проценты',
                            data: interests,
                            borderColor: '#ffc107',
                            backgroundColor: 'rgba(255, 193, 7, 0.1)',
                            tension: 0.1
                        }, {
                            label: 'Основной долг',
                            data: principals,
                            borderColor: '#0dcaf0',
                            backgroundColor: 'rgba(13, 202, 240, 0.1)',
                            tension: 0.1
                        }]
                    },
                    options: {
                        responsive: true,
                        plugins: {
                            title: {
                                display: true,
                                text: 'График платежей по кредиту'
                            }
                        },
                        scales: {
                            y: {
                                beginAtZero: true,
                                ticks: {
                                    callback: function(value) {
                                        return value.toLocaleString() + ' ₽';
                                    }
                                }
                            }
                        }
                    }
                });
            }
        }
    }

    /**
     * Настройка графика прогресса
     */
    setupProgressChart() {
        const progressCanvas = document.getElementById('progress-chart');
        if (progressCanvas && typeof Chart !== 'undefined') {
            const ctx = progressCanvas.getContext('2d');

            // Получить данные о погашении
            const totalPayments = document.querySelectorAll('.schedule-table tbody tr').length;
            const paidPayments = document.querySelectorAll('.schedule-table tbody tr.paid').length;
            const remainingPayments = totalPayments - paidPayments;

            new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: ['Погашено', 'Осталось'],
                    datasets: [{
                        data: [paidPayments, remainingPayments],
                        backgroundColor: ['#198754', '#e9ecef'],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: {
                            position: 'bottom'
                        },
                        title: {
                            display: true,
                            text: 'Прогресс погашения кредита'
                        }
                    }
                }
            });
        }
    }

    /**
     * Показать уведомление
     */
    showNotification(message, type = 'success') {
        const notification = document.createElement('div');
        notification.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
        notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';

        // Безопасно добавить сообщение
        notification.appendChild(document.createTextNode(message));

        // Создать кнопку закрытия
        const closeButton = document.createElement('button');
        closeButton.type = 'button';
        closeButton.className = 'btn-close';
        closeButton.setAttribute('data-bs-dismiss', 'alert');
        notification.appendChild(closeButton);

        document.body.appendChild(notification);

        // Автоматически скрыть через 5 секунд
        setTimeout(() => {
            if (notification.parentNode) {
                notification.remove();
            }
        }, 5000);
    }
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
    new LoanManager();
});

// Экспорт для использования в других модулях
window.LoanManager = LoanManager;
