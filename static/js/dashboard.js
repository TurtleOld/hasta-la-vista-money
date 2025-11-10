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

    /* ========= helpers (безопасное построение DOM) ========= */

    _el(tag, attrs = {}, ...children) {
        const node = document.createElement(tag);
        for (const [k, v] of Object.entries(attrs || {})) {
            if (k === 'class') node.className = v;
            else if (k === 'dataset' && v && typeof v === 'object') {
                for (const [dk, dv] of Object.entries(v)) node.dataset[dk] = String(dv);
            } else if (k === 'style' && v && typeof v === 'object') {
                Object.assign(node.style, v);
            } else if (k in node && k !== 'role' && k !== 'ariaLabel') {
                try { node[k] = v; } catch { node.setAttribute(k, v); }
            } else if (k === 'role') {
                node.setAttribute('role', v);
            } else if (k === 'ariaLabel') {
                node.setAttribute('aria-label', v);
            } else {
                node.setAttribute(k, v);
            }
        }
        for (const child of children.flat()) {
            if (child == null) continue;
            if (child instanceof Node) node.appendChild(child);
            else node.appendChild(document.createTextNode(String(child)));
        }
        return node;
    }

    _icon(classList) {
        return this._el('i', { class: classList });
    }

    _clear(node) {
        if (!node) return;
        while (node.firstChild) node.removeChild(node.firstChild);
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
            const qs = new URLSearchParams({ period: this.period });
            const url = `${this.apiBase}/data/?${qs.toString()}`;

            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                credentials: 'same-origin',
            });

            if (!response.ok) {
                let errorText = '';
                try {
                    const errorData = await response.json();
                    errorText = errorData.error || JSON.stringify(errorData);
                    if (errorData.traceback) {
                        console.error('Traceback:', errorData.traceback);
                    }
                } catch {
                    errorText = await response.text();
                }
                throw new Error(`Failed to load dashboard data: ${response.status} ${response.statusText}. ${errorText}`);
            }

            const data = await response.json();

            this.widgets = data.widgets || [];
            this.analyticsData = data.analytics || {};
            this.comparisonData = data.comparison || {};
            this.recentTransactions = data.recent_transactions || [];

            this.renderWidgets();
        } catch (error) {
            console.error('Error loading dashboard:', error);
            const errorMessage = error.message || 'Ошибка загрузки данных дашборда';
            this.showError(errorMessage);
        }
    }

    renderWidgets() {
        const grid = document.getElementById('widgets-grid');
        if (!grid) return;

        this._clear(grid);

        if (this.widgets.length === 0) {
            const empty = this._el('div', { class: 'dashboard-empty-state' },
                this._icon('bi bi-graph-up fs-1 text-muted'),
                this._el('p', { class: 'text-muted' }, 'Добавьте виджеты для отображения данных'),
            );
            grid.appendChild(empty);
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
        const div = this._el('div', {
            class: 'widget',
            dataset: { widgetId: widget.id, width: widget.width || 6 },
        });
        div.style.setProperty('--widget-height', `${widget.height || 300}px`);

        const header = this._el('div', { class: 'widget-header' });

        const h5 = this._el('h5');
        // Безопасно вставляем заголовок как текст
        h5.textContent = this.getWidgetTitle(widget.widget_type);

        const controls = this._el('div', { class: 'widget-controls' });
        const btnCfg = this._el('button', { class: 'btn-config-widget', title: 'Настройки', type: 'button', ariaLabel: 'Настройки' }, this._icon('bi bi-gear'));
        const btnDel = this._el('button', { class: 'btn-remove-widget', title: 'Удалить', type: 'button', ariaLabel: 'Удалить' }, this._icon('bi bi-x-circle'));
        controls.append(btnCfg, btnDel);

        header.append(h5, controls);

        const content = this._el('div', { class: 'widget-content', id: `widget-content-${widget.id}` });
        const loading = this._el('div', { class: 'widget-loading' },
            this._el('div', { class: 'spinner-border spinner-border-sm', role: 'status' },
                this._el('span', { class: 'visually-hidden' }, 'Загрузка...')
            )
        );

        const chartContainer = this._el('div', {
            class: 'widget-chart',
            id: `chart-${widget.id}`
        });
        chartContainer.style.height = `${widget.height || 300}px`;

        content.append(loading, chartContainer);
        div.append(header, content);

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
        // Возвращаем строку, которая дальше кладётся в textContent (безопасно)
        return titles[widgetType] || String(widgetType || 'Виджет');
    }

    renderWidgetCharts() {
        this.widgets.forEach((widget) => {
            const chartId = `chart-${widget.id}`;
            const chartContainer = document.getElementById(chartId);
            if (!chartContainer) return;

            const contentDiv = chartContainer.parentElement;
            contentDiv?.classList.remove('loading', 'error');

            const loadingDiv = contentDiv?.querySelector('.widget-loading');
            loadingDiv?.remove();

            try {
                let chart = this.charts.get(widget.id);
                window.destroyChart?.(chart);

                chart = this.renderWidgetChart(widget, chartId);
                if (chart) {
                    this.charts.set(widget.id, chart);
                } else {
                    contentDiv?.classList.add('error');
                    const err = this._el('div', { class: 'error' },
                        this._icon('bi bi-exclamation-triangle'),
                        this._el('p', null, 'Не удалось отобразить виджет'),
                    );
                    this._clear(contentDiv);
                    contentDiv?.appendChild(err);
                }
            } catch (error) {
                console.error(`Error rendering widget ${widget.id}:`, error);
                contentDiv?.classList.add('error');
                const err = this._el('div', { class: 'error' },
                    this._icon('bi bi-exclamation-triangle'),
                    this._el('p', null, 'Ошибка отображения виджета'),
                );
                this._clear(contentDiv);
                contentDiv?.appendChild(err);
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
            case 'recent_transactions':
                return this.renderRecentTransactions(widget, containerId);
            default:
                return null;
        }
    }

    renderBalanceChart(widget, containerId, initChart, chartConfigs) {
        const config = JSON.parse(JSON.stringify(chartConfigs.balance));
        const stats = this.analyticsData?.stats;
        if (!stats?.months_data) return null;

        const labels = stats.months_data.map((m) => m.month);
        const balances = stats.months_data.map((m) => {
            if (m.balance !== undefined) return parseFloat(m.balance.toFixed(2));
            return parseFloat((m.income - m.expenses).toFixed(2));
        });

        config.xAxis.data = labels;
        config.series[0].data = balances;

        config.tooltip.formatter = function (params) {
            if (!params || params.length === 0) return '';
            const param = params[0];
            const value = typeof param.value === 'number'
                ? param.value
                : (Array.isArray(param.value) ? param.value[1] : param.value);
            const formattedValue = parseFloat(value).toFixed(2);
            // Возвращает строку для тултипа графика (это не DOM-вставка)
            return `${param.axisValue}<br/>Баланс: ${formattedValue}`;
        };

        return initChart(containerId, config);
    }

    renderExpensesChart(widget, containerId, initChart, chartConfigs) {
        const config = JSON.parse(JSON.stringify(chartConfigs.expensesTrend));
        const stats = this.analyticsData?.stats;
        if (!stats?.months_data) return null;

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
        window.addDrillDownHandler?.(chart, (params) => this.handleDrillDown('expense', params));
        return chart;
    }

    renderIncomeChart(widget, containerId, initChart, chartConfigs) {
        const config = JSON.parse(JSON.stringify(chartConfigs.incomeTrend));
        const stats = this.analyticsData?.stats;
        if (!stats?.months_data) return null;

        const labels = stats.months_data.map((m) => m.month);
        const income = stats.months_data.map((m) => m.income);

        config.xAxis.data = labels;
        config.series[0].data = income;

        return initChart(containerId, config);
    }

    renderComparisonChart(widget, containerId, initChart, chartConfigs) {
        const config = JSON.parse(JSON.stringify(chartConfigs.comparison));
        if (!this.comparisonData?.current) return null;

        const current = this.comparisonData.current;
        const previous = this.comparisonData.previous;

        config.series[0].data = [current.expenses, current.income, current.savings];
        config.series[1].data = [previous.expenses, previous.income, previous.savings];

        return initChart(containerId, config);
    }

    renderTrendChart(widget, containerId, initChart, chartConfigs) {
        const config = JSON.parse(JSON.stringify(chartConfigs.expensesTrend));
        const stats = this.analyticsData?.stats;
        if (!stats?.months_data) return null;

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
                    return d.toLocaleDateString('ru-RU', { month: 'short', year: 'numeric' });
                });
                const forecastValues = trends.forecast.map((f) => f.value);
                config.xAxis.data = [...labels, ...forecastLabels];
                config.series[0].data = [...expenses, ...Array(forecastLabels.length).fill(null)];
                config.series[2].data = [...Array(labels.length).fill(null), ...forecastValues];
            }
        }

        return initChart(containerId, config);
    }

    renderTopCategoriesChart(widget, containerId, initChart, chartConfigs) {
        const config = JSON.parse(JSON.stringify(chartConfigs.categoryDrillDown));
        const stats = this.analyticsData?.stats;
        if (!stats?.top_expense_categories) return null;

        const categories = stats.top_expense_categories.slice(0, 10);
        const data = categories.map((cat) => ({
            value: parseFloat(cat.total),
            name: cat.category__name,
        }));

        config.series[0].data = data;

        const chart = initChart(containerId, config);
        window.addDrillDownHandler?.(chart, (params) => this.handleDrillDown('expense', params));
        return chart;
    }

    renderRecentTransactions(widget, containerId) {
        const container = document.getElementById(containerId);
        if (!container) return null;

        const transactions = this.recentTransactions || [];
        const contentDiv = container.parentElement;
        contentDiv?.classList.remove('loading', 'error');

        this._clear(container);

        if (transactions.length === 0) {
            const empty = this._el('div', { class: 'text-center text-muted py-4' },
                this._icon('bi bi-inbox fs-3'),
                this._el('p', { class: 'mt-2' }, 'Нет последних операций'),
            );
            container.appendChild(empty);
            return null;
        }

        const list = this._el('div', { class: 'list-group list-group-flush' });

        const formatDate = (dateStr) => {
            const date = new Date(dateStr);
            return date.toLocaleDateString('ru-RU', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric',
            });
        };

        const amountNode = (amount, type) => {
            const num = Number(amount);
            const formatted = isFinite(num)
                ? num.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                : String(amount);
            const sign = type === 'expense' ? '-' : '+';
            const cls = type === 'expense' ? 'text-danger' : 'text-success';
            return this._el('span', { class: cls }, `${sign}${formatted} ₽`);
        };

        const typeIconNode = (type) => {
            return (type === 'expense')
                ? this._icon('bi bi-arrow-down-circle text-danger')
                : this._icon('bi bi-arrow-up-circle text-success');
        };

        for (const t of transactions) {
            const row = this._el('div', { class: 'list-group-item border-0 px-0 py-2' },
                this._el('div', { class: 'd-flex justify-content-between align-items-start' },
                    this._el('div', { class: 'flex-grow-1' },
                        this._el('div', { class: 'd-flex align-items-center gap-2 mb-1' },
                            typeIconNode(t.type),
                            this._el('strong', null, String(t.category ?? '')),
                        ),
                        this._el('small', { class: 'text-muted d-block' },
                            this._icon('bi bi-wallet2'), ' ',
                            String(t.account ?? '')
                        ),
                        this._el('small', { class: 'text-muted' },
                            this._icon('bi bi-calendar3'), ' ',
                            formatDate(t.date)
                        ),
                    ),
                    this._el('div', { class: 'text-end' }, amountNode(t.amount, t.type))
                )
            );
            list.appendChild(row);
        }

        container.appendChild(list);
        return null;
    }

    async handleDrillDown(type, params) {
        const categoryName = params?.name;
        const stats = this.analyticsData?.stats;
        if (!stats?.top_expense_categories || !categoryName) return;

        const category = stats.top_expense_categories.find(
            (cat) => cat.category__name === categoryName
        );
        if (!category?.category__id) return;

        try {
            const qs = new URLSearchParams({
                category_id: String(category.category__id),
                type: String(type),
            });
            const response = await fetch(`${this.apiBase}/drilldown/?${qs.toString()}`);
            const data = await response.json();

            if (data.data && data.data.length > 0) {
                this.updateChartWithDrillDown(params.componentIndex, data);
            }
        } catch (error) {
            console.error('Error loading drill-down data:', error);
        }
    }

    updateChartWithDrillDown(chartIndex, drillData) {
        const chartConfigs = window.chartConfigs;
        if (!chartConfigs?.categoryDrillDown) return;

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
        if (!grid || this.sortable) return;

        this.sortable = Sortable.create(grid, {
            animation: 150,
            handle: '.widget-header',
            onEnd: () => this.updateWidgetPositions(),
        });
    }

    async updateWidgetPositions() {
        const widgets = Array.from(document.querySelectorAll('.widget'));
        const positions = widgets.map((widget, index) => ({
            id: parseInt(widget.dataset.widgetId, 10),
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
            if (!modal) modal = new bootstrap.Modal(modalElement);
            modal.show();
        } catch (error) {
            console.error('Error showing modal:', error);
        }
    }

    async addWidget(widgetType) {
        const modalElement = document.getElementById('widget-select-modal');
        if (modalElement) {
            const modal = bootstrap.Modal.getInstance(modalElement);
            modal?.hide();
        }
        if (!widgetType) {
            console.error('Widget type is required');
            return;
        }

        try {
            const csrfToken = this.getCsrfToken();
            if (!csrfToken) throw new Error('CSRF token not found');

            const response = await fetch(`${this.apiBase}/widget/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                },
                body: JSON.stringify({
                    widget_type: String(widgetType),
                    position: this.widgets.length,
                    config: {},
                }),
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.error || 'Failed to create widget');
            }

            await this.loadDashboard();
        } catch (error) {
            console.error('Error adding widget:', error);
            this.showError('Ошибка добавления виджета: ' + (error?.message || 'Неизвестная ошибка'));
        }
    }

    async removeWidget(widgetId) {
        if (!confirm('Удалить этот виджет?')) return;

        try {
            const response = await fetch(`${this.apiBase}/widget/?widget_id=${encodeURIComponent(widgetId)}`, {
                method: 'DELETE',
                headers: { 'X-CSRFToken': this.getCsrfToken() },
            });

            if (!response.ok) throw new Error('Failed to delete widget');

            const chart = this.charts.get(parseInt(widgetId, 10));
            window.destroyChart?.(chart);
            this.charts.delete(parseInt(widgetId, 10));

            await this.loadDashboard();
        } catch (error) {
            console.error('Error removing widget:', error);
            this.showError('Ошибка удаления виджета');
        }
    }

    showConfigModal(widgetId) {
        const widget = this.widgets.find((w) => w.id === parseInt(widgetId, 10));
        if (!widget) return;

        const idInput = document.getElementById('config-widget-id');
        const widthInput = document.getElementById('config-width');
        const heightInput = document.getElementById('config-height');

        if (idInput) idInput.value = String(widgetId);
        if (widthInput) widthInput.value = String(widget.width || 6);
        if (heightInput) heightInput.value = String(widget.height || 300);

        const modalEl = document.getElementById('widget-config-modal');
        if (!modalEl) return;
        const modal = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl);
        modal.show();
    }

    async saveWidgetConfig() {
        const idEl = document.getElementById('config-widget-id');
        const wEl = document.getElementById('config-width');
        const hEl = document.getElementById('config-height');

        const widgetId = parseInt(idEl?.value ?? '0', 10);
        const width = parseInt(wEl?.value ?? '6', 10);
        const height = parseInt(hEl?.value ?? '300', 10);

        const widget = this.widgets.find((w) => w.id === widgetId);
        if (!widget) return;

        try {
            await this.saveWidgetConfigToServer({
                widget_id: widgetId,
                width,
                height,
                config: widget.config,
            });

            const modal = bootstrap.Modal.getInstance(document.getElementById('widget-config-modal'));
            modal?.hide();

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

        if (!response.ok) throw new Error('Failed to save widget config');
        return response.json();
    }

    toggleEditMode() {
        this.editMode = !this.editMode;
        const grid = document.getElementById('widgets-grid');
        const btn = document.getElementById('edit-mode-btn');

        if (grid) {
            grid.classList.toggle('edit-mode', this.editMode);
        }
        if (btn) {
            // Не используем небезопасный innerHTML; строим кнопку с иконкой
            this._clear(btn);
            if (this.editMode) {
                btn.appendChild(document.createTextNode('Завершить редактирование'));
            } else {
                btn.append(this._icon('bi bi-pencil'), document.createTextNode(' Редактировать'));
            }
        }
    }

    getCsrfToken() {
        let token = null;

        const inp = document.querySelector('[name=csrfmiddlewaretoken]');
        if (inp) token = inp.value;

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
        // Безопасный алерт без innerHTML
        let region = document.getElementById('alerts-region');
        if (!region) {
            region = this._el('div', { id: 'alerts-region' });
            document.body.prepend(region);
        }

        const alert = this._el('div', {
            class: 'alert alert-danger alert-dismissible fade show',
            role: 'alert'
        });

        const text = this._el('span', null, String(message));
        const btn = this._el('button', {
            type: 'button',
            class: 'btn-close',
            ariaLabel: 'Close'
        });

        btn.addEventListener('click', () => alert.remove());

        alert.append(text, btn);
        region.prepend(alert);

        const timer = setTimeout(() => alert.remove(), 5000);
        btn.addEventListener('click', () => clearTimeout(timer));
    }
}

window.DashboardManager = DashboardManager;
