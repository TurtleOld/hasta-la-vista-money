'use strict';

/* global Chart */

(function() {
    const balanceTrendWidget = {
        period: '30d',
        groupId: 'my',
        chartInstance: null,

        init: function() {
            const widget = document.getElementById('balance-trend-widget');
            if (!widget) {
                return;
            }

            const dataElement = widget.querySelector('[data-balance-trend]');
            if (dataElement) {
                try {
                    const data = JSON.parse(dataElement.textContent);
                    this.period = data.period || '30d';
                    this.groupId = data.groupId || 'my';
                } catch (e) {
                    console.error('[BalanceTrendWidget] Error parsing widget data:', e);
                }
            }

            this.attachPeriodButtonListeners();
            
            const chartContainer = widget.querySelector('[data-has-data]');
            if (chartContainer && chartContainer.textContent === 'true') {
                this.renderChart();
            }
        },

        attachPeriodButtonListeners: function() {
            const buttons = document.querySelectorAll('#balance-trend-widget .period-btn');
            buttons.forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    const period = btn.dataset.period;
                    this.changePeriod(period);
                });
            });
        },

        changePeriod: function(period) {
            const params = new URLSearchParams(window.location.search);
            params.set('balance_trend_period', period);
            const safeUrl = window.location.pathname + '?' + params.toString();
            if (safeUrl.startsWith('/') || safeUrl.startsWith(window.location.origin)) {
                window.location.href = encodeURI(safeUrl);
            }
        },

        renderChart: function() {
            const canvas = document.getElementById('balance-trend-chart');
            if (!canvas || typeof Chart === 'undefined') {
                console.warn('[BalanceTrendWidget] Chart.js not available or canvas not found');
                return;
            }

            // Get series data from data attribute
            const widget = document.getElementById('balance-trend-widget');
            const dataElement = widget.querySelector('[data-series]');
            
            if (!dataElement) {
                console.warn('[BalanceTrendWidget] No series data found');
                return;
            }

            let seriesData;
            try {
                seriesData = JSON.parse(dataElement.textContent);
            } catch (e) {
                console.error('[BalanceTrendWidget] Error parsing series data:', e);
                return;
            }

            if (!seriesData || seriesData.length === 0) {
                return;
            }

            const ctx = canvas.getContext('2d');

            // Prepare chart data
            const labels = seriesData.map(point => {
                const date = new Date(point.date);
                return date.toLocaleDateString('ru-RU', { month: 'short', day: 'numeric' });
            });

            const data = seriesData.map(point => point.balance);

            // Determine color based on trend
            const firstBalance = data[0];
            const lastBalance = data[data.length - 1];
            const isPositive = lastBalance >= firstBalance;
            const borderColor = isPositive ? 'rgb(34, 197, 94)' : 'rgb(239, 68, 68)';
            const backgroundColor = isPositive
                ? 'rgba(34, 197, 94, 0.1)'
                : 'rgba(239, 68, 68, 0.1)';

            // Destroy existing chart if present
            if (this.chartInstance) {
                this.chartInstance.destroy();
            }

            // Create new chart
            this.chartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Balance (₽)',
                        data: data,
                        borderColor: borderColor,
                        backgroundColor: backgroundColor,
                        borderWidth: 2,
                        fill: true,
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        pointBackgroundColor: borderColor,
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2,
                        tension: 0.4,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {
                        legend: {
                            display: false,
                        },
                        tooltip: {
                            backgroundColor: 'rgba(0, 0, 0, 0.8)',
                            padding: 12,
                            titleColor: '#fff',
                            bodyColor: '#fff',
                            borderColor: borderColor,
                            borderWidth: 1,
                            displayColors: false,
                            callbacks: {
                                label: function(context) {
                                    return context.parsed.y.toLocaleString('ru-RU', {
                                        minimumFractionDigits: 2,
                                        maximumFractionDigits: 2,
                                    }) + ' ₽';
                                }
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: false,
                            ticks: {
                                color: 'rgb(107, 114, 128)',
                                callback: function(value) {
                                    return value.toLocaleString('ru-RU', {
                                        minimumFractionDigits: 0,
                                        maximumFractionDigits: 0,
                                    });
                                }
                            },
                            grid: {
                                color: 'rgba(107, 114, 128, 0.1)',
                                drawBorder: false,
                            }
                        },
                        x: {
                            ticks: {
                                color: 'rgb(107, 114, 128)',
                            },
                            grid: {
                                display: false,
                                drawBorder: false,
                            }
                        }
                    }
                }
            });
        }
    };

    // Initialize when DOM is ready
    function initBalanceTrendWidget() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                balanceTrendWidget.init();
            });
        } else {
            balanceTrendWidget.init();
        }
    }

    // Start initialization
    initBalanceTrendWidget();

    // Export for external use if needed
    window.BalanceTrendWidget = balanceTrendWidget;
})();
