'use strict';

class DashboardManager {
    #apiBase = '/users/dashboard/';

    constructor() {
        this.widgets = [];
        this.charts = new Map();
        this.editMode = false;
        this.period = 'month';
        this.sortable = null;
        this.init();
    }
    _el(tag, attrs = {}, ...children) {
        const node = document.createElement(tag);

        const propWhitelist = new Set([
            'id', 'class', 'title', 'type', 'value', 'role', 'ariaLabel'
        ]);

        for (const [kRaw, v] of Object.entries(attrs || {})) {
            const k = String(kRaw);
            if (k === '__proto__' || k === 'prototype' || k === 'constructor') continue;
            if (/^on/i.test(k)) continue;

            if (k === 'class') {
                node.className = String(v);
                continue;
            }
            if (k === 'style' && v && typeof v === 'object') {
                Object.assign(node.style, v);
                continue;
            }
            if (k === 'dataset' && v && typeof v === 'object') {
                for (const [dkRaw, dv] of Object.entries(v)) {
                    const dk = String(dkRaw);
                    if (dk === '__proto__' || dk === 'prototype' || dk === 'constructor') continue;
                    if (!/^[A-Za-z0-9_]+$/.test(dk)) continue;
                    const dataAttrName = 'data-' + dk.replace(/_/g, '-');
                    node.setAttribute(dataAttrName, String(dv));
                }
                continue;
            }
            if (propWhitelist.has(k)) {
                if (k === 'id') {
                    node.id = String(v);
                } else if (k === 'title') {
                    node.title = String(v);
                } else if (k === 'type') {
                    node.type = String(v);
                } else if (k === 'value') {
                    node.value = String(v);
                } else if (k === 'role') {
                    node.setAttribute('role', String(v));
                } else if (k === 'ariaLabel') {
                    node.setAttribute('aria-label', String(v));
                }
                continue;
            }
            if (/^aria-[a-z0-9-]+$/.test(k)) {
                node.setAttribute(k, String(v));
            }
        }

        for (const child of children.flat()) {
            if (child == null) continue;
            if (child instanceof Node) node.appendChild(child);
            else node.appendChild(document.createTextNode(String(child)));
        }
        return node;
    }

    _icon(cls) { return this._el('i', { class: cls }); }

    _clear(node) { if (node) while (node.firstChild) node.removeChild(node.firstChild); }

    _createSVG(paths, attrs = {}) {
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        if (attrs.class) svg.setAttribute('class', String(attrs.class));
        svg.setAttribute('fill', String(attrs.fill || 'none'));
        svg.setAttribute('stroke', String(attrs.stroke || 'currentColor'));
        svg.setAttribute('viewBox', String(attrs.viewBox || '0 0 24 24'));

        if (attrs.width) svg.setAttribute('width', String(attrs.width));
        if (attrs.height) svg.setAttribute('height', String(attrs.height));

        if (Array.isArray(paths) && paths.length > 0) {
            paths.forEach(path => {
                if (!path || !path.d) return;
                const pathEl = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                pathEl.setAttribute('stroke-linecap', String(path.strokeLinecap || 'round'));
                pathEl.setAttribute('stroke-linejoin', String(path.strokeLinejoin || 'round'));
                pathEl.setAttribute('stroke-width', String(path.strokeWidth || '2'));
                pathEl.setAttribute('d', String(path.d));
                svg.appendChild(pathEl);
            });
        }
        return svg;
    }

    _buildURL(relativePath, params) {
        const path = String(relativePath || '');

        if (!path || path.trim() === '') {
            throw new Error('Empty path provided');
        }

        const trimmedPath = path.trim();

        if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(trimmedPath)) {
            throw new Error('Protocol not allowed in path');
        }

        if (trimmedPath.includes('//')) {
            throw new Error('Double slash not allowed in path');
        }

        const basePath = this.#apiBase.endsWith('/') ? this.#apiBase : this.#apiBase + '/';
        const full = trimmedPath.startsWith('/') ? trimmedPath : basePath + trimmedPath;
        const url = new URL(full, window.location.origin);

        if (url.origin !== window.location.origin) {
            throw new Error('Cross-origin URL not allowed');
        }

        if (!['http:', 'https:'].includes(url.protocol)) {
            throw new Error('Only HTTP/HTTPS protocols allowed');
        }

        if (!url.pathname.startsWith(basePath)) {
            throw new Error('Blocked unexpected path');
        }

        if (params && typeof params === 'object') {
            for (const [k, v] of Object.entries(params)) {
                url.searchParams.set(k, String(v));
            }
        }
        return url.toString();
    }

    async _safeFetch(relativePath, urlParams = null, fetchOptions = {}) {
        const validatedUrl = this._buildURL(relativePath, urlParams);
        return window.fetch(validatedUrl, fetchOptions);
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

        if (!addWidgetBtn) {
            console.warn('add-widget-btn not found');
        } else {
            addWidgetBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                console.log('Add widget button clicked');
                try {
                    this.showWidgetSelectModal();
                } catch (err) {
                    console.error('Error showing widget select modal:', err);
                }
            });
        }

        if (!editModeBtn) {
            console.warn('edit-mode-btn not found');
        } else {
            editModeBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                console.log('Edit mode button clicked');
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
                e.preventDefault(); e.stopPropagation();
                this.addWidget(widgetSelectBtn.dataset.widgetType);
                return;
            }

            const removeBtn = e.target.closest('.btn-remove-widget');
            if (removeBtn) {
                e.preventDefault();
                const widget = removeBtn.closest('.widget');
                if (widget) this.removeWidget(widget.dataset.widgetId);
                return;
            }

            const configBtn = e.target.closest('.btn-config-widget');
            if (configBtn) {
                e.preventDefault();
                const widget = configBtn.closest('.widget');
                const widgetId = widget?.dataset.widgetId;
                if (widgetId) this.showConfigModal(widgetId);
            }
        });
    }

    async loadDashboard() {
        try {
            const response = await this._safeFetch('data/', { period: this.period }, {
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
            this.showError(error.message || 'Ошибка загрузки данных дашборда');
        }
    }

    renderWidgets() {
        const grid = document.getElementById('widgets-grid');
        if (!grid) return;

        this._clear(grid);

        if (this.widgets.length === 0) {
            const emptyState = this._el('div', { class: 'dashboard-empty-state' });
            const svg = this._createSVG([{
                d: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z'
            }], {
                class: 'w-16 h-16 mx-auto mb-4 text-gray-400 dark:text-gray-500'
            });
            const p = this._el('p', { class: 'text-lg font-medium text-gray-600 dark:text-gray-400' });
            p.textContent = 'Добавьте виджеты для отображения данных';
            emptyState.appendChild(svg);
            emptyState.appendChild(p);
            grid.appendChild(emptyState);
            return;
        }

        this.widgets.forEach((widget) => grid.appendChild(this.createWidgetElement(widget)));
        this.initSortable();
        this.renderWidgetCharts();
    }

    createWidgetElement(widget) {
        const div = this._el('div', { class: 'widget', dataset: { widgetId: widget.id, width: widget.width || 6 } });
        div.style.setProperty('--widget-width', widget.width || 6);
        div.style.setProperty('--widget-height', `${widget.height || 300}px`);

        const header = this._el('div', { class: 'widget-header' });
        const title = this._el('h5', { class: 'text-lg font-semibold text-gray-900 dark:text-white' });
        title.textContent = this.getWidgetTitle(widget.widget_type);

        const controls = this._el('div', { class: 'widget-controls' });
        const configBtn = this._el('button', {
            class: 'btn-config-widget text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200',
            title: 'Настройки',
            type: 'button',
            ariaLabel: 'Настройки'
        });
        const configSvg = this._createSVG([
            { d: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z' },
            { d: 'M15 12a3 3 0 11-6 0 3 3 0 016 0z' }
        ], { class: 'w-5 h-5' });
        configBtn.appendChild(configSvg);

        const removeBtn = this._el('button', {
            class: 'btn-remove-widget text-gray-500 hover:text-red-600 dark:text-gray-400 dark:hover:text-red-400',
            title: 'Удалить',
            type: 'button',
            ariaLabel: 'Удалить'
        });
        const removeSvg = this._createSVG([{
            d: 'M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z'
        }], { class: 'w-5 h-5' });
        removeBtn.appendChild(removeSvg);

        controls.append(configBtn, removeBtn);
        header.append(title, controls);

        const content = this._el('div', { class: 'widget-content', id: `widget-content-${widget.id}` });
        const loadingDiv = this._el('div', { class: 'widget-loading flex items-center justify-center h-full' });
        const spinner = this._el('div', { class: 'animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 dark:border-blue-400' });
        loadingDiv.appendChild(spinner);
        content.appendChild(loadingDiv);

        const chartContainer = this._el('div', { class: 'widget-chart', id: `chart-${widget.id}` });
        chartContainer.style.height = `${widget.height || 300}px`;
        content.appendChild(chartContainer);

        div.append(header, content);
        return div;
    }

    getWidgetTitle(widgetType) {
        switch (widgetType) {
            case 'balance': return 'Баланс счетов';
            case 'expenses_chart': return 'График расходов';
            case 'income_chart': return 'График доходов';
            case 'comparison': return 'Сравнение периодов';
            case 'trend': return 'Тренды и прогнозы';
            case 'top_categories': return 'Топ категорий';
            case 'recent_transactions': return 'Последние операции';
            default: return String(widgetType || 'Виджет');
        }
    }

    renderWidgetCharts() {
        this.widgets.forEach((widget) => {
            const chartId = `chart-${widget.id}`;
            const chartContainer = document.getElementById(chartId);
            if (!chartContainer) return;

            const contentDiv = chartContainer.parentElement;
            contentDiv?.classList.remove('loading', 'error');
            contentDiv?.querySelector('.widget-loading')?.remove();

            try {
                let chart = this.charts.get(widget.id);
                window.destroyChart?.(chart);

                chart = this.renderWidgetChart(widget, chartId);
                if (chart) {
                    this.charts.set(widget.id, chart);
                } else {
                    contentDiv?.classList.add('error');
                    this._clear(contentDiv);
                    const errorDiv = this._el('div', { class: 'flex flex-col items-center justify-center h-full text-center p-4 text-red-600 dark:text-red-400' });
                    const errorSvg = this._createSVG([{
                        d: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z'
                    }], { class: 'w-12 h-12 mb-2' });
                    const errorP = this._el('p', { class: 'font-medium' });
                    errorP.textContent = 'Не удалось отобразить виджет';
                    errorDiv.appendChild(errorSvg);
                    errorDiv.appendChild(errorP);
                    contentDiv?.appendChild(errorDiv);
                }
            } catch (error) {
                console.error(`Error rendering widget ${widget.id}:`, error);
                contentDiv?.classList.add('error');
                this._clear(contentDiv);
                const errorDiv = this._el('div', { class: 'flex flex-col items-center justify-center h-full text-center p-4 text-red-600 dark:text-red-400' });
                const errorSvg = this._createSVG([{
                    d: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z'
                }], { class: 'w-12 h-12 mb-2' });
                const errorP = this._el('p', { class: 'font-medium' });
                errorP.textContent = 'Ошибка отображения виджета';
                errorDiv.appendChild(errorSvg);
                errorDiv.appendChild(errorP);
                contentDiv?.appendChild(errorDiv);
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
            case 'balance': return this.renderBalanceChart(widget, containerId, initChart, chartConfigs);
            case 'expenses_chart': return this.renderExpensesChart(widget, containerId, initChart, chartConfigs);
            case 'income_chart': return this.renderIncomeChart(widget, containerId, initChart, chartConfigs);
            case 'comparison': return this.renderComparisonChart(widget, containerId, initChart, chartConfigs);
            case 'trend': return this.renderTrendChart(widget, containerId, initChart, chartConfigs);
            case 'top_categories': return this.renderTopCategoriesChart(widget, containerId, initChart, chartConfigs);
            case 'recent_transactions': return this.renderRecentTransactions(widget, containerId);
            default: return null;
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
            const p = params[0];
            const value = typeof p.value === 'number' ? p.value : (Array.isArray(p.value) ? p.value[1] : p.value);
            return `${p.axisValue}<br/>Баланс: ${parseFloat(value).toFixed(2)}`;
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
        config.series[0].data = categories.map((cat) => ({
            value: parseFloat(cat.total),
            name: cat.category__name,
        }));

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
            const emptyDiv = this._el('div', { class: 'text-center text-gray-500 dark:text-gray-400 py-8' });
            const emptySvg = this._createSVG([{
                d: 'M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4'
            }], { class: 'w-12 h-12 mx-auto mb-2' });
            const emptyP = this._el('p', { class: 'mt-2 font-medium' });
            emptyP.textContent = 'Нет последних операций';
            emptyDiv.appendChild(emptySvg);
            emptyDiv.appendChild(emptyP);
            container.appendChild(emptyDiv);
            return null;
        }

        const list = this._el('div', { class: 'divide-y divide-gray-200 dark:divide-gray-700' });

        const formatDate = (dateStr) => {
            const date = new Date(dateStr);
            return date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
        };
        const amountNode = (amount, type) => {
            const num = Number(amount);
            const formatted = isFinite(num)
                ? num.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                : String(amount);
            const sign = type === 'expense' ? '-' : '+';
            const cls = type === 'expense'
                ? 'text-red-600 dark:text-red-400 font-semibold'
                : 'text-green-600 dark:text-green-400 font-semibold';
            const span = this._el('span', { class: cls });
            span.textContent = `${sign}${formatted} ₽`;
            return span;
        };

        for (const t of transactions) {
            const item = this._el('div', { class: 'py-3 px-2 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors' });
            const itemContent = this._el('div', { class: 'flex justify-between items-start gap-4' });

            const leftDiv = this._el('div', { class: 'flex-1 min-w-0' });
            const iconRow = this._el('div', { class: 'flex items-center gap-2 mb-1' });

            const typeIcon = t.type === 'expense'
                ? this._createSVG([{ d: 'M19 14l-7 7m0 0l-7-7m7 7V3' }], { class: 'w-5 h-5 text-red-500 flex-shrink-0' })
                : this._createSVG([{ d: 'M5 10l7-7m0 0l7 7m-7-7v18' }], { class: 'w-5 h-5 text-green-500 flex-shrink-0' });

            const categoryStrong = this._el('strong', { class: 'text-gray-900 dark:text-white font-medium' });
            categoryStrong.textContent = String(t.category ?? '');

            iconRow.appendChild(typeIcon);
            iconRow.appendChild(categoryStrong);

            const infoRow = this._el('div', { class: 'flex flex-wrap gap-3 text-sm text-gray-600 dark:text-gray-400 mt-1' });

            const accountSpan = this._el('span', { class: 'flex items-center gap-1' });
            const accountSvg = this._createSVG([{
                d: 'M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z'
            }], { class: 'w-4 h-4' });
            accountSpan.appendChild(accountSvg);
            const accountText = document.createTextNode(String(t.account ?? ''));
            accountSpan.appendChild(accountText);

            const dateSpan = this._el('span', { class: 'flex items-center gap-1' });
            const dateSvg = this._createSVG([{
                d: 'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z'
            }], { class: 'w-4 h-4' });
            dateSpan.appendChild(dateSvg);
            const dateText = document.createTextNode(formatDate(t.date));
            dateSpan.appendChild(dateText);

            infoRow.appendChild(accountSpan);
            infoRow.appendChild(dateSpan);

            leftDiv.appendChild(iconRow);
            leftDiv.appendChild(infoRow);

            const rightDiv = this._el('div', { class: 'text-right flex-shrink-0' });
            rightDiv.appendChild(amountNode(t.amount, t.type));

            itemContent.appendChild(leftDiv);
            itemContent.appendChild(rightDiv);
            item.appendChild(itemContent);
            list.appendChild(item);
        }

        container.appendChild(list);
        return null;
    }

    async handleDrillDown(type, params) {
        const categoryName = params?.name;
        const stats = this.analyticsData?.stats;
        if (!stats?.top_expense_categories || !categoryName) return;

        const category = stats.top_expense_categories.find((c) => c.category__name === categoryName);
        if (!category?.category__id) return;

        try {
            const response = await this._safeFetch('drilldown/', {
                category_id: String(category.category__id),
                type: String(type),
            });
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

        if (typeof Sortable === 'undefined') {
            console.warn('Sortable.js is not loaded. Drag and drop functionality will not work.');
            return;
        }

        try {
            this.sortable = Sortable.create(grid, {
                animation: 150,
                handle: '.widget-header',
                onEnd: () => this.updateWidgetPositions(),
            });
        } catch (error) {
            console.error('Error initializing Sortable:', error);
        }
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
        console.log('Showing widget select modal');
        modalElement.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
        this.setupModalCloseHandlers(modalElement);
    }

    async addWidget(widgetType) {
        const modalElement = document.getElementById('widget-select-modal');
        if (modalElement) {
            this.hideModal(modalElement);
        }
        if (!widgetType) { console.error('Widget type is required'); return; }

        try {
            const csrfToken = this.getCsrfToken();
            if (!csrfToken) throw new Error('CSRF token not found');

            const response = await this._safeFetch('widget/', null, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
                body: JSON.stringify({ widget_type: String(widgetType), position: this.widgets.length, config: {} }),
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
        const id = parseInt(String(widgetId), 10);
        if (!Number.isInteger(id) || id < 0) { this.showError('Некорректный идентификатор виджета'); return; }

        try {
            const response = await this._safeFetch('widget/', { widget_id: id }, {
                method: 'DELETE',
                headers: { 'X-CSRFToken': this.getCsrfToken() },
            });

            if (!response.ok) throw new Error('Failed to delete widget');

            const chart = this.charts.get(id);
            window.destroyChart?.(chart);
            this.charts.delete(id);

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
        modalEl.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
        this.setupModalCloseHandlers(modalEl);
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
            await this.saveWidgetConfigToServer({ widget_id: widgetId, width, height, config: widget.config });

            const modalEl = document.getElementById('widget-config-modal');
            if (modalEl) {
                this.hideModal(modalEl);
            }

            await this.loadDashboard();
        } catch (error) {
            console.error('Error saving widget config:', error);
            this.showError('Ошибка сохранения настроек');
        }
    }

    async saveWidgetConfigToServer(config) {
        const response = await this._safeFetch('widget/', null, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.getCsrfToken() },
            body: JSON.stringify(config),
        });
        if (!response.ok) throw new Error('Failed to save widget config');
        return response.json();
    }

    toggleEditMode() {
        this.editMode = !this.editMode;
        const grid = document.getElementById('widgets-grid');
        const btn = document.getElementById('edit-mode-btn');

        grid?.classList.toggle('edit-mode', this.editMode);

        if (btn) {
            this._clear(btn);
            if (this.editMode) {
                const checkSvg = this._createSVG([{ d: 'M5 13l4 4L19 7' }], { class: 'w-5 h-5' });
                const checkText = document.createTextNode(' Завершить редактирование');
                btn.appendChild(checkSvg);
                btn.appendChild(checkText);
            } else {
                const editSvg = this._createSVG([{
                    d: 'M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z'
                }], { class: 'w-5 h-5' });
                const editText = document.createTextNode(' Редактировать');
                btn.appendChild(editSvg);
                btn.appendChild(editText);
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
                const [name, val] = cookie.trim().split('=');
                if (name === 'csrftoken') { token = val; break; }
            }
        }
        return token || '';
    }

    hideModal(modalElement) {
        if (!modalElement) return;
        modalElement.classList.add('hidden');
        document.body.style.overflow = '';
    }

    setupModalCloseHandlers(modalElement) {
        const backdrop = modalElement.querySelector('.modal-backdrop');
        const closeButtons = modalElement.querySelectorAll('.modal-close');

        const closeHandler = (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.hideModal(modalElement);
        };

        if (backdrop) {
            backdrop.removeEventListener('click', closeHandler);
            backdrop.addEventListener('click', closeHandler);
        }

        closeButtons.forEach(btn => {
            btn.removeEventListener('click', closeHandler);
            btn.addEventListener('click', closeHandler);
        });
    }

    showError(message) {
        let region = document.getElementById('alerts-region');
        if (!region) {
            region = this._el('div', { id: 'alerts-region', class: 'fixed top-4 right-4 z-50 max-w-md w-full px-4' });
            document.body.prepend(region);
        }
        const alert = this._el('div', {
            class: 'bg-red-50 dark:bg-red-900/20 border-l-4 border-red-500 dark:border-red-400 p-4 rounded-lg shadow-lg mb-4 flex items-start gap-3',
            role: 'alert'
        });

        const errorSvg = this._createSVG([{
            d: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z'
        }], { class: 'w-6 h-6 text-red-600 dark:text-red-400 flex-shrink-0' });

        const messageDiv = this._el('div', { class: 'flex-1' });
        const messageP = this._el('p', { class: 'text-sm font-medium text-red-800 dark:text-red-200' });
        messageP.textContent = String(message);
        messageDiv.appendChild(messageP);

        const closeBtn = this._el('button', {
            type: 'button',
            class: 'text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-200',
            ariaLabel: 'Close'
        });
        const closeSvg = this._createSVG([{
            d: 'M6 18L18 6M6 6l12 12'
        }], { class: 'w-5 h-5' });
        closeBtn.appendChild(closeSvg);

        alert.appendChild(errorSvg);
        alert.appendChild(messageDiv);
        alert.appendChild(closeBtn);

        closeBtn.addEventListener('click', () => alert.remove());
        region.prepend(alert);
        const timer = setTimeout(() => alert.remove(), 5000);
        closeBtn.addEventListener('click', () => clearTimeout(timer));
    }
}

window.DashboardManager = DashboardManager;

(function() {
    function initDashboard() {
        const grid = document.getElementById('widgets-grid');
        if (!grid) {
            console.error('Widgets grid not found');
            return false;
        }

        const addWidgetBtn = document.getElementById('add-widget-btn');
        const editModeBtn = document.getElementById('edit-mode-btn');

        if (!addWidgetBtn) {
            console.warn('add-widget-btn element not found in DOM');
        }
        if (!editModeBtn) {
            console.warn('edit-mode-btn element not found in DOM');
        }

        if (window.chartConfigs && window.initChart && window.DashboardManager) {
            if (typeof Sortable === 'undefined') {
                console.warn('Sortable.js is not loaded. Drag and drop will not work.');
            }
            console.log('Initializing DashboardManager...');
            try {
                window.dashboardManager = new window.DashboardManager();
                console.log('DashboardManager initialized successfully');
                return true;
            } catch (error) {
                console.error('Error initializing DashboardManager:', error);
                return false;
            }
        } else {
            console.warn('Dashboard dependencies not ready:', {
                chartConfigs: !!window.chartConfigs,
                initChart: !!window.initChart,
                DashboardManager: !!window.DashboardManager,
                Sortable: typeof Sortable !== 'undefined'
            });
        }
        return false;
    }

    function waitForDependencies(attempts = 0) {
        if (attempts > 20) {
            console.error('Failed to load dashboard dependencies after 20 attempts');
            return;
        }

        if (initDashboard()) {
            console.log('Dashboard initialized successfully');
            return;
        }

        setTimeout(() => {
            waitForDependencies(attempts + 1);
        }, 100);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            waitForDependencies();
        });
    } else {
        waitForDependencies();
    }
})();
