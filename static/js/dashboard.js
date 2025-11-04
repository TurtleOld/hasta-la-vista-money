class DashboardManager {
    constructor() {
        this.widgets = [];
        this.charts = new Map();
        this.editMode = false;
        this.period = 'month';
        this.sortable = null;
        this.apiBase = '/users/dashboard';
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.loadDashboard();
    }

    setupEventListeners() {
        const addWidgetBtn = document.getElementById('add-widget-btn');
        const editModeBtn = document.getElementById('edit-mode-btn');
        const periodSelect = document.getElementById('period-select');
        const saveConfigBtn = document.getElementById('save-widget-config');

        if (addWidgetBtn) {
            addWidgetBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                console.log('Add widget button clicked');
                try {
                    this.showWidgetSelectModal();
                } catch (error) {
                    console.error('Error in showWidgetSelectModal:', error);
                }
            });
        } else {
            console.error('Add widget button not found');
        }

        if (editModeBtn) {
            editModeBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this.toggleEditMode();
            });
        }

        if (periodSelect) {
            periodSelect.addEventListener('change', (e) => {
                this.period = e.target.value;
                this.loadDashboard();
            });
        }

        if (saveConfigBtn) {
            saveConfigBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this.saveWidgetConfig();
            });
        }

        document.addEventListener('click', (e) => {
            const widgetSelectBtn = e.target.closest('.widget-select-btn');
            if (widgetSelectBtn) {
                e.preventDefault();
                e.stopPropagation();
                const widgetType = widgetSelectBtn.dataset.widgetType;
                console.log('Widget selected:', widgetType);
                this.addWidget(widgetType);
                return;
            }

            const removeBtn = e.target.closest('.btn-remove-widget');
            if (removeBtn) {
                e.preventDefault();
                const widget = removeBtn.closest('.widget');
                if (widget) {
                    const widgetId = widget.dataset.widgetId;
                    this.removeWidget(widgetId);
                }
                return;
            }

            const configBtn = e.target.closest('.btn-config-widget');
            if (configBtn) {
                e.preventDefault();
                const widget = configBtn.closest('.widget');
                const widgetId = widget?.dataset.widgetId;
                if (widgetId) {
                    this.showConfigModal(widgetId);
                }
            }
        });
    }

    async loadDashboard() {
        try {
            const url = `${this.apiBase}/data/?period=${this.period}`;
            console.log('Loading dashboard from:', url);
            
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                credentials: 'same-origin',
            });

            console.log('Response status:', response.status, response.statusText);

            if (!response.ok) {
                let errorText = '';
                try {
                    const errorData = await response.json();
                    errorText = errorData.error || JSON.stringify(errorData);
                    console.error('Error response:', errorData);
                    if (errorData.traceback) {
                        console.error('Traceback:', errorData.traceback);
                    }
                } catch (e) {
                    errorText = await response.text();
                    console.error('Error response (text):', errorText);
                }
                throw new Error(`Failed to load dashboard data: ${response.status} ${response.statusText}. ${errorText}`);
            }

            const data = await response.json();
            console.log('Dashboard data loaded successfully:', data);
            
            this.widgets = data.widgets || [];
            this.analyticsData = data.analytics || {};
            this.comparisonData = data.comparison || {};

            this.renderWidgets();
        } catch (error) {
            console.error('Error loading dashboard:', error);
            const errorMessage = error.message || 'Ошибка загрузки данных дашборда';
            console.error('Full error details:', {
                name: error.name,
                message: error.message,
                stack: error.stack,
            });
            this.showError(errorMessage);
        }
    }

    renderWidgets() {
        const grid = document.getElementById('widgets-grid');
        if (!grid) {
            return;
        }

        grid.innerHTML = '';

        if (this.widgets.length === 0) {
            grid.innerHTML = `
                <div class="dashboard-empty-state">
                    <i class="bi bi-graph-up fs-1 text-muted"></i>
                    <p class="text-muted">Добавьте виджеты для отображения данных</p>
                </div>
            `;
            return;
        }

        this.widgets.forEach((widget) => {
            const widgetElement = this.createWidgetElement(widget);
            grid.appendChild(widgetElement);
        });

        this.initSortable();
        this.renderWidgetCharts();
    }

    createWidgetElement(widget) {
        const div = document.createElement('div');
        div.className = 'widget';
        div.dataset.widgetId = widget.id;
        div.dataset.width = widget.width || 6;
        div.style.setProperty('--widget-height', `${widget.height || 300}px`);

        const widgetTitle = this.getWidgetTitle(widget.widget_type);

        div.innerHTML = `
            <div class="widget-header">
                <h5>${widgetTitle}</h5>
                <div class="widget-controls">
                    <button class="btn-config-widget" title="Настройки">
                        <i class="bi bi-gear"></i>
                    </button>
                    <button class="btn-remove-widget" title="Удалить">
                        <i class="bi bi-x-circle"></i>
                    </button>
                </div>
            </div>
            <div class="widget-content" id="widget-content-${widget.id}">
                <div class="widget-loading">
                    <div class="spinner-border spinner-border-sm" role="status">
                        <span class="visually-hidden">Загрузка...</span>
                    </div>
                </div>
            </div>
        `;

        const chartContainer = document.createElement('div');
        chartContainer.className = 'widget-chart';
        chartContainer.id = `chart-${widget.id}`;
        chartContainer.style.height = `${widget.height || 300}px`;

        const contentDiv = div.querySelector('.widget-content');
        contentDiv.appendChild(chartContainer);

        return div;
    }

    getWidgetTitle(widgetType) {
        const titles = {
            'balance': 'Баланс счетов',
            'expenses_chart': 'График расходов',
            'income_chart': 'График доходов',
            'comparison': 'Сравнение периодов',
            'trend': 'Тренды и прогнозы',
            'top_categories': 'Топ категорий',
            'recent_transactions': 'Последние операции',
        };
        return titles[widgetType] || widgetType;
    }

    renderWidgetCharts() {
        this.widgets.forEach((widget) => {
            const chartId = `chart-${widget.id}`;
            const chartContainer = document.getElementById(chartId);

            if (!chartContainer) {
                return;
            }

            const contentDiv = chartContainer.parentElement;
            contentDiv.classList.remove('loading', 'error');

            try {
                let chart = this.charts.get(widget.id);
                window.destroyChart?.(chart);

                chart = this.renderWidgetChart(widget, chartId);
                if (chart) {
                    this.charts.set(widget.id, chart);
                } else {
                    contentDiv.classList.add('error');
                    contentDiv.innerHTML = `
                        <div class="error">
                            <i class="bi bi-exclamation-triangle"></i>
                            <p>Не удалось отобразить виджет</p>
                        </div>
                    `;
                }
            } catch (error) {
                console.error(`Error rendering widget ${widget.id}:`, error);
                contentDiv.classList.add('error');
                contentDiv.innerHTML = `
                    <div class="error">
                        <i class="bi bi-exclamation-triangle"></i>
                        <p>Ошибка отображения виджета</p>
                    </div>
                `;
            }
        });
    }

    renderWidgetChart(widget, containerId) {
        if (!window.initChart || !window.chartConfigs) {
            console.error('Chart utilities not loaded');
            return null;
        }

        const initChart = window.initChart;
        const chartConfigs = window.chartConfigs;

        switch (widget.widget_type) {
            case 'balance':
                return this.renderBalanceChart(widget, containerId, initChart, chartConfigs);
            case 'expenses_chart':
                return this.renderExpensesChart(widget, containerId, initChart, chartConfigs);
            case 'income_chart':
                return this.renderIncomeChart(widget, containerId, initChart, chartConfigs);
            case 'comparison':
                return this.renderComparisonChart(widget, containerId, initChart, chartConfigs);
            case 'trend':
                return this.renderTrendChart(widget, containerId, initChart, chartConfigs);
            case 'top_categories':
                return this.renderTopCategoriesChart(widget, containerId, initChart, chartConfigs);
            default:
                return null;
        }
    }

    renderBalanceChart(widget, containerId, initChart, chartConfigs) {
        const config = JSON.parse(JSON.stringify(chartConfigs.balance));
        const stats = this.analyticsData?.stats;

        if (!stats?.months_data) {
            return null;
        }

        const labels = stats.months_data.map((m) => m.month);
        const balances = stats.months_data.map((m) => m.income - m.expenses);

        config.xAxis.data = labels;
        config.series[0].data = balances;

        const chart = initChart(containerId, config);
        return chart;
    }

    renderExpensesChart(widget, containerId, initChart, chartConfigs) {
        const config = JSON.parse(JSON.stringify(chartConfigs.expensesTrend));
        const stats = this.analyticsData?.stats;

        if (!stats?.months_data) {
            return null;
        }

        const labels = stats.months_data.map((m) => m.month);
        const expenses = stats.months_data.map((m) => m.expenses);

        config.xAxis.data = labels;
        config.series[0].data = expenses;

        const trends = this.analyticsData?.trends;
        if (trends?.trend_line) {
            const trendValues = trends.trend_line.map((t) => t.value);
            config.series[1].data = trendValues;

            if (trends.forecast) {
                const forecastLabels = trends.forecast.map((f) => f.date);
                const forecastValues = trends.forecast.map((f) => f.value);
                config.xAxis.data = [...labels, ...forecastLabels];
                config.series[0].data = [...expenses, ...Array(forecastLabels.length).fill(null)];
                config.series[2].data = [...Array(labels.length).fill(null), ...forecastValues];
            }
        }

        const chart = initChart(containerId, config);

        window.addDrillDownHandler?.(chart, (params) => {
            this.handleDrillDown('expense', params);
        });

        return chart;
    }

    renderIncomeChart(widget, containerId, initChart, chartConfigs) {
        const config = JSON.parse(JSON.stringify(chartConfigs.incomeTrend));
        const stats = this.analyticsData?.stats;

        if (!stats?.months_data) {
            return null;
        }

        const labels = stats.months_data.map((m) => m.month);
        const income = stats.months_data.map((m) => m.income);

        config.xAxis.data = labels;
        config.series[0].data = income;

        const chart = initChart(containerId, config);
        return chart;
    }

    renderComparisonChart(widget, containerId, initChart, chartConfigs) {
        const config = JSON.parse(JSON.stringify(chartConfigs.comparison));

        if (!this.comparisonData?.current) {
            return null;
        }

        const current = this.comparisonData.current;
        const previous = this.comparisonData.previous;

        config.series[0].data = [
            current.expenses,
            current.income,
            current.savings,
        ];
        config.series[1].data = [
            previous.expenses,
            previous.income,
            previous.savings,
        ];

        const chart = initChart(containerId, config);
        return chart;
    }

    renderTrendChart(widget, containerId, initChart, chartConfigs) {
        const config = JSON.parse(JSON.stringify(chartConfigs.expensesTrend));
        const stats = this.analyticsData?.stats;

        if (!stats?.months_data) {
            return null;
        }

        const labels = stats.months_data.map((m) => m.month);
        const expenses = stats.months_data.map((m) => m.expenses);

        config.xAxis.data = labels;
        config.series[0].data = expenses;

        const trends = this.analyticsData?.trends;
        if (trends && trends.trend_line) {
            const trendValues = trends.trend_line.map((t) => t.value);
            config.series[1].data = trendValues;

            if (trends.forecast) {
                const forecastLabels = trends.forecast.map((f) => {
                    const d = new Date(f.date);
                    return d.toLocaleDateString('ru-RU', {month: 'short', year: 'numeric'});
                });
                const forecastValues = trends.forecast.map((f) => f.value);
                config.xAxis.data = [...labels, ...forecastLabels];
                config.series[0].data = [...expenses, ...Array(forecastLabels.length).fill(null)];
                config.series[2].data = [...Array(labels.length).fill(null), ...forecastValues];
            }
        }

        const chart = initChart(containerId, config);
        return chart;
    }

    renderTopCategoriesChart(widget, containerId, initChart, chartConfigs) {
        const config = JSON.parse(JSON.stringify(chartConfigs.categoryDrillDown));
        const stats = this.analyticsData?.stats;

        if (!stats?.top_expense_categories) {
            return null;
        }

        const categories = stats.top_expense_categories.slice(0, 10);
        const data = categories.map((cat) => ({
            value: parseFloat(cat.total),
            name: cat.category__name,
        }));

        config.series[0].data = data;

        const chart = initChart(containerId, config);

        window.addDrillDownHandler?.(chart, (params) => {
            this.handleDrillDown('expense', params);
        });

        return chart;
    }

    async handleDrillDown(type, params) {
        const categoryName = params.name;
        const stats = this.analyticsData?.stats;

        if (!stats?.top_expense_categories) {
            return;
        }

        const category = stats.top_expense_categories.find(
            (cat) => cat.category__name === categoryName
        );

        if (!category?.category__id) {
            return;
        }

        try {
            const response = await fetch(
                `${this.apiBase}/drilldown/?category_id=${category.category__id}&type=${type}`
            );
            const data = await response.json();

            if (data.data && data.data.length > 0) {
                this.updateChartWithDrillDown(params.componentIndex, data);
            }
        } catch (error) {
            console.error('Error loading drill-down data:', error);
        }
    }

    updateChartWithDrillDown(chartIndex, drillData) {
        const config = JSON.parse(JSON.stringify(chartConfigs.categoryDrillDown));
        config.series[0].data = drillData.data.map((item) => ({
            value: item.value,
            name: item.name,
        }));

            const chart = this.charts.get(chartIndex);
            window.updateChartOption?.(chart, config);
        }

    initSortable() {
        const grid = document.getElementById('widgets-grid');
        if (!grid || this.sortable) {
            return;
        }

        this.sortable = Sortable.create(grid, {
            animation: 150,
            handle: '.widget-header',
            onEnd: (evt) => {
                this.updateWidgetPositions();
            },
        });
    }

    async updateWidgetPositions() {
        const widgets = Array.from(document.querySelectorAll('.widget'));
        const positions = widgets.map((widget, index) => ({
            id: parseInt(widget.dataset.widgetId),
            position: index,
        }));

        for (const pos of positions) {
            const widget = this.widgets.find((w) => w.id === pos.id);
            if (widget) {
                widget.position = pos.position;
                await this.saveWidgetConfigToServer({
                    widget_id: pos.id,
                    position: pos.position,
                    config: widget.config,
                });
            }
        }
    }

    showWidgetSelectModal() {
        const modalElement = document.getElementById('widget-select-modal');
        if (!modalElement) {
            console.error('Widget select modal not found');
            return;
        }

        if (typeof bootstrap === 'undefined') {
            console.error('Bootstrap is not loaded');
            return;
        }
        
        try {
            let modal = bootstrap.Modal.getInstance(modalElement);
            if (!modal) {
                modal = new bootstrap.Modal(modalElement);
            }
            modal.show();
            console.log('Modal shown successfully');
        } catch (error) {
            console.error('Error showing modal:', error);
        }
    }

    async addWidget(widgetType) {
        const modalElement = document.getElementById('widget-select-modal');
        if (modalElement) {
            const modal = bootstrap.Modal.getInstance(modalElement);
            if (modal) {
                modal.hide();
            }
        }

        if (!widgetType) {
            console.error('Widget type is required');
            return;
        }

        try {
            const csrfToken = this.getCsrfToken();
            if (!csrfToken) {
                throw new Error('CSRF token not found');
            }

            const response = await fetch(`${this.apiBase}/widget/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                },
                body: JSON.stringify({
                    widget_type: widgetType,
                    position: this.widgets.length,
                    config: {},
                }),
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.error || 'Failed to create widget');
            }

            const result = await response.json();
            console.log('Widget added:', result);

            await this.loadDashboard();
        } catch (error) {
            console.error('Error adding widget:', error);
            this.showError('Ошибка добавления виджета: ' + error.message);
        }
    }

    async removeWidget(widgetId) {
        if (!confirm('Удалить этот виджет?')) {
            return;
        }

        try {
            const response = await fetch(`${this.apiBase}/widget/?widget_id=${widgetId}`, {
                method: 'DELETE',
                headers: {
                    'X-CSRFToken': this.getCsrfToken(),
                },
            });

            if (!response.ok) {
                throw new Error('Failed to delete widget');
            }

            const chart = this.charts.get(parseInt(widgetId));
            window.destroyChart?.(chart);
            this.charts.delete(parseInt(widgetId));

            await this.loadDashboard();
        } catch (error) {
            console.error('Error removing widget:', error);
            this.showError('Ошибка удаления виджета');
        }
    }

    showConfigModal(widgetId) {
        const widget = this.widgets.find((w) => w.id === parseInt(widgetId));
        if (!widget) {
            return;
        }

        document.getElementById('config-widget-id').value = widgetId;
        document.getElementById('config-width').value = widget.width || 6;
        document.getElementById('config-height').value = widget.height || 300;

        const modal = new bootstrap.Modal(document.getElementById('widget-config-modal'));
        modal.show();
    }

    async saveWidgetConfig() {
        const widgetId = parseInt(document.getElementById('config-widget-id').value);
        const width = parseInt(document.getElementById('config-width').value);
        const height = parseInt(document.getElementById('config-height').value);

        const widget = this.widgets.find((w) => w.id === widgetId);
        if (!widget) {
            return;
        }

        try {
            await this.saveWidgetConfigToServer({
                widget_id: widgetId,
                width: width,
                height: height,
                config: widget.config,
            });

            const modal = bootstrap.Modal.getInstance(document.getElementById('widget-config-modal'));
            if (modal) {
                modal.hide();
            }

            await this.loadDashboard();
        } catch (error) {
            console.error('Error saving widget config:', error);
            this.showError('Ошибка сохранения настроек');
        }
    }

    async saveWidgetConfigToServer(config) {
        const response = await fetch(`${this.apiBase}/widget/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCsrfToken(),
            },
            body: JSON.stringify(config),
        });

        if (!response.ok) {
            throw new Error('Failed to save widget config');
        }

        return response.json();
    }

    toggleEditMode() {
        this.editMode = !this.editMode;
        const grid = document.getElementById('widgets-grid');
        const btn = document.getElementById('edit-mode-btn');

        if (grid) {
            if (this.editMode) {
                grid.classList.add('edit-mode');
                if (btn) {
                    btn.textContent = 'Завершить редактирование';
                }
            } else {
                grid.classList.remove('edit-mode');
                if (btn) {
                    btn.innerHTML = '<i class="bi bi-pencil"></i> Редактировать';
                }
            }
        }
    }

    getCsrfToken() {
        let token = null;

        if (document.querySelector('[name=csrfmiddlewaretoken]')) {
            token = document.querySelector('[name=csrfmiddlewaretoken]').value;
        }

        if (!token) {
            const cookies = document.cookie.split(';');
            for (const cookie of cookies) {
                const parts = cookie.trim().split('=');
                if (parts.length === 2 && parts[0] === 'csrftoken') {
                    token = parts[1];
                    break;
                }
            }
        }

        return token || '';
    }

    showError(message) {
        const alert = document.createElement('div');
        alert.className = 'alert alert-danger alert-dismissible fade show';
        alert.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        document.body.insertBefore(alert, document.body.firstChild);

        setTimeout(() => {
            alert.remove();
        }, 5000);
    }
}

window.DashboardManager = DashboardManager;

