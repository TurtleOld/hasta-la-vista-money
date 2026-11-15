'use strict';

/* global Chart */

(function() {
    const balanceTrendWidget = {
        period: '30d',
        groupId: 'my',
        chartInstance: null,
        /* Canvas the current chart was drawn on; HTMX OOB swaps replace it. */
        renderedCanvas: null,

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

            const chartContainer = widget.querySelector('[data-has-data]');
            if (!chartContainer || chartContainer.textContent !== 'true') {
                return;
            }
            const canvas = widget.querySelector('[data-balance-trend-chart]');
            /* htmx fires afterSwap for every swapped/OOB element; only draw
               when the canvas element itself is new. Re-creating the chart on
               the same canvas leaves its backing store at the canvas default
               size while CSS stretches it, which inflates tick labels. */
            if (
                canvas &&
                canvas === this.renderedCanvas &&
                window.Chart &&
                window.Chart.getChart(canvas)
            ) {
                return;
            }
            this.renderChart();
        },

        renderChart: function() {
            const canvas = document.querySelector('[data-balance-trend-chart]');
            if (!canvas || typeof Chart === 'undefined') {
                console.warn('[BalanceTrendWidget] Chart.js not available or canvas not found');
                return;
            }

            // Get series data from json_script tag
            const dataElement = document.getElementById('balance-trend-series');

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

            // Destroy any chart instance bound to this canvas. Chart.js keeps
            // a registry per <canvas>, so HTMX-replacing the canvas leaves the
            // previous instance pointing at a detached node — clean it up via
            // the static getter to avoid "Canvas is already in use" errors.
            const existing = Chart.getChart(canvas);
            if (existing) {
                existing.destroy();
            }
            this.chartInstance = null;

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
            this.renderedCanvas = canvas;
        }
    };

    /* Drop charts whose canvas htmx is removing (OOB widget swaps bypass
       hx-target), so no instance keeps resizing a detached canvas. */
    document.addEventListener('htmx:beforeCleanupElement', (event) => {
        const elt = event.detail && event.detail.elt;
        if (!elt || !elt.querySelector || typeof window.Chart === 'undefined') {
            return;
        }
        const canvas = elt.matches('[data-balance-trend-chart]')
            ? elt
            : elt.querySelector('[data-balance-trend-chart]');
        if (!canvas) {
            return;
        }
        const chart = window.Chart.getChart(canvas);
        if (chart) {
            chart.destroy();
        }
        if (balanceTrendWidget.renderedCanvas === canvas) {
            balanceTrendWidget.renderedCanvas = null;
        }
    });

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
