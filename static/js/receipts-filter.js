/* eslint-env browser */

(function() {
    'use strict';

    const state = {
        selectedProducts: new Set(),
        autocompleteResults: [],
        currentFocus: -1,
        debounceTimer: null,
        isDropdownVisible: false,
        allProductsCache: null,
    };

    const elements = {
        productInput: null,
        selectedProductsContainer: null,
        selectedProductsPlaceholder: null,
        autocompleteDropdown: null,
        selectedProductsInput: null,
        spinner: null,
        filterForm: null,
        productInputWrapper: null,
    };

    function init() {
        initFilterCollapse();
        initPeriodPresets();

        elements.productInput = document.getElementById('product-autocomplete');
        elements.selectedProductsContainer = document.getElementById('selected-products-container');
        elements.selectedProductsPlaceholder = document.getElementById('selected-products-placeholder');
        elements.autocompleteDropdown = document.getElementById('product-autocomplete-dropdown');
        elements.selectedProductsInput = document.getElementById('selected-products-input');
        elements.spinner = document.getElementById('product-input-spinner');
        elements.filterForm = document.getElementById('receipts-filter-form');

        if (!elements.productInput) return;

        elements.productInputWrapper = elements.productInput.parentElement;

        loadSelectedProductsFromUrl();
        attachEventListeners();
        updateActiveFilterCount();
    }

    function initFilterCollapse() {
        const filterCollapse = document.getElementById('filterCollapse');
        const toggleButton = document.getElementById('filterToggle');

        if (!filterCollapse || !toggleButton) return;

        function toggleCollapse() {
            const isExpanded = toggleButton.getAttribute('aria-expanded') === 'true';
            if (isExpanded) {
                filterCollapse.classList.add('hidden');
                toggleButton.setAttribute('aria-expanded', 'false');
            } else {
                filterCollapse.classList.remove('hidden');
                toggleButton.setAttribute('aria-expanded', 'true');
            }
        }

        if (window.location.search.length > 1) {
            filterCollapse.classList.remove('hidden');
            toggleButton.setAttribute('aria-expanded', 'true');
        }

        toggleButton.addEventListener('click', function(e) {
            e.preventDefault();
            toggleCollapse();
        });
    }

    function initPeriodPresets() {
        const chips = document.querySelectorAll('[data-period]');
        if (!chips.length) return;

        const dateFromInput = document.getElementById('id_receipt_date_0');
        const dateToInput = document.getElementById('id_receipt_date_1');
        if (!dateFromInput || !dateToInput) return;

        function formatDate(date) {
            const d = String(date.getDate()).padStart(2, '0');
            const m = String(date.getMonth() + 1).padStart(2, '0');
            const y = date.getFullYear();
            return `${d}/${m}/${y}`;
        }

        function getPresetRange(preset) {
            const today = new Date();
            const y = today.getFullYear();
            const mo = today.getMonth();
            const d = today.getDate();

            switch (preset) {
                case 'today':
                    return { from: new Date(y, mo, d), to: new Date(y, mo, d) };
                case 'week': {
                    const dow = today.getDay();
                    const monday = new Date(y, mo, d - ((dow + 6) % 7));
                    return { from: monday, to: new Date(y, mo, d) };
                }
                case 'month':
                    return { from: new Date(y, mo, 1), to: new Date(y, mo, d) };
                case 'last_month':
                    return { from: new Date(y, mo - 1, 1), to: new Date(y, mo, 0) };
                case 'quarter':
                    return { from: new Date(y, Math.floor(mo / 3) * 3, 1), to: new Date(y, mo, d) };
                case 'year':
                    return { from: new Date(y, 0, 1), to: new Date(y, mo, d) };
                default:
                    return null;
            }
        }

        chips.forEach(function(chip) {
            chip.addEventListener('click', function() {
                const range = getPresetRange(chip.dataset.period);
                if (!range) return;

                dateFromInput.value = formatDate(range.from);
                dateToInput.value = formatDate(range.to);

                chips.forEach(c => c.classList.remove('is-active'));
                chip.classList.add('is-active');

                updateActiveFilterCount();
            });
        });

        // Highlight matching chip on page load based on current date values
        syncPeriodChips(chips, dateFromInput, dateToInput, formatDate, getPresetRange);
    }

    function syncPeriodChips(chips, dateFromInput, dateToInput, formatDate, getPresetRange) {
        const curFrom = dateFromInput.value;
        const curTo = dateToInput.value;
        if (!curFrom && !curTo) return;

        const presets = ['today', 'week', 'month', 'last_month', 'quarter', 'year'];
        for (const preset of presets) {
            const range = getPresetRange(preset);
            if (!range) continue;
            if (formatDate(range.from) === curFrom && formatDate(range.to) === curTo) {
                chips.forEach(function(chip) {
                    chip.classList.toggle('is-active', chip.dataset.period === preset);
                });
                break;
            }
        }
    }

    function loadSelectedProductsFromUrl() {
        const urlParams = new URLSearchParams(window.location.search);
        const productNames = urlParams.get('product_names');
        if (!productNames) return;

        try {
            const products = decodeURIComponent(productNames).split(',').map(p => p.trim()).filter(Boolean);
            products.forEach(p => state.selectedProducts.add(p));
            renderSelectedProducts();
        } catch (e) {
            console.error('Error loading products from URL:', e);
        }
    }

    function attachEventListeners() {
        elements.productInput.addEventListener('input', debounce(handleInput, 300));
        elements.productInput.addEventListener('keydown', handleKeydown);
        elements.productInput.addEventListener('blur', handleBlur);
        elements.productInput.addEventListener('focus', handleFocus);
        document.addEventListener('click', handleDocumentClick);

        if (elements.filterForm) {
            elements.filterForm.addEventListener('submit', handleFormSubmit);
        }

        // Update badge on any filter input change
        const filterInputs = document.querySelectorAll(
            '#receipts-filter-form input[name="receipt_date_0"], ' +
            '#receipts-filter-form input[name="receipt_date_1"], ' +
            '#receipts-filter-form input[type="number"], ' +
            '#receipts-filter-form select'
        );
        filterInputs.forEach(function(input) {
            input.addEventListener('change', updateActiveFilterCount);
        });
    }

    async function handleInput() {
        const query = elements.productInput.value.trim();
        hideSpinner();

        if (query.length === 0) {
            hideDropdown();
            return;
        }

        showSpinner();
        try {
            const response = await fetchWithAuth(`/api/receipts/product-autocomplete/?q=${encodeURIComponent(query)}`);
            hideSpinner();
            if (!response.ok) { hideDropdown(); return; }

            const data = await response.json();
            state.autocompleteResults = (data.results || []).filter(p => !state.selectedProducts.has(p));
            state.allProductsCache = null;
            showDropdown(false);
        } catch (e) {
            hideSpinner();
            hideDropdown();
        }
    }

    async function showAllProducts() {
        if (elements.productInput.value.trim()) return;

        if (state.allProductsCache) {
            state.autocompleteResults = state.allProductsCache.filter(p => !state.selectedProducts.has(p));
            showDropdown(true);
            return;
        }

        showSpinner();
        try {
            const response = await fetchWithAuth('/api/receipts/product-autocomplete/?q=');
            hideSpinner();
            if (!response.ok) return;

            const data = await response.json();
            state.allProductsCache = data.results || [];
            state.autocompleteResults = state.allProductsCache.filter(p => !state.selectedProducts.has(p));
            showDropdown(true);
        } catch (e) {
            hideSpinner();
        }
    }

    function handleKeydown(e) {
        const items = elements.autocompleteDropdown.querySelectorAll('.autocomplete-item');

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            state.currentFocus++;
            setActiveItem(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            state.currentFocus--;
            setActiveItem(items);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (state.currentFocus > -1 && items[state.currentFocus]) {
                items[state.currentFocus].click();
            } else if (elements.productInput.value.trim()) {
                addProduct(elements.productInput.value.trim());
                elements.productInput.value = '';
                hideDropdown();
            }
        } else if (e.key === 'Escape') {
            hideDropdown();
        } else if (e.key === 'Backspace' && elements.productInput.value === '' && state.selectedProducts.size > 0) {
            const lastProduct = Array.from(state.selectedProducts).pop();
            removeProduct(lastProduct);
        }
    }

    function handleBlur() {
        setTimeout(() => hideDropdown(), 200);
    }

    function handleFocus() {
        const query = elements.productInput.value.trim();
        if (query) {
            handleInput();
        } else {
            showAllProducts();
        }
    }

    function handleDocumentClick(e) {
        if (!elements.productInput.contains(e.target) && !elements.autocompleteDropdown.contains(e.target)) {
            hideDropdown();
        }
    }

    function handleFormSubmit() {
        elements.selectedProductsInput.value = Array.from(state.selectedProducts).join(',');
    }

    function showDropdown(isAll) {
        const wrapperRect = elements.productInputWrapper.getBoundingClientRect();
        const dropdownComputedStyle = window.getComputedStyle(elements.autocompleteDropdown);
        const marginTop = parseFloat(dropdownComputedStyle.marginTop) || 4;

        elements.autocompleteDropdown.style.position = 'fixed';
        elements.autocompleteDropdown.style.left = `${wrapperRect.left}px`;
        elements.autocompleteDropdown.style.top = `${wrapperRect.bottom + marginTop}px`;
        elements.autocompleteDropdown.style.width = `${wrapperRect.width}px`;

        elements.autocompleteDropdown.innerHTML = '';

        if (!state.autocompleteResults.length) {
            if (isAll) {
                const empty = document.createElement('div');
                empty.className = 'autocomplete-item-empty';
                empty.textContent = 'Нет товаров для выбора';
                elements.autocompleteDropdown.appendChild(empty);
            } else {
                hideDropdown();
                return;
            }
        } else {
            if (isAll) {
                const header = document.createElement('div');
                header.className = 'autocomplete-item-header';
                header.textContent = 'Все товары';
                elements.autocompleteDropdown.appendChild(header);
            }

            state.autocompleteResults.forEach((product, index) => {
                const item = document.createElement('div');
                item.className = 'autocomplete-item';
                item.textContent = product;
                item.dataset.index = index;

                item.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    addProduct(product);
                    elements.productInput.value = '';
                    // Refresh "all products" view after selection
                    state.allProductsCache = null;
                    hideDropdown();
                    elements.productInput.focus();
                });

                elements.autocompleteDropdown.appendChild(item);
            });
        }

        elements.autocompleteDropdown.classList.remove('hidden');
        state.isDropdownVisible = true;
        state.currentFocus = -1;
    }

    function hideDropdown() {
        elements.autocompleteDropdown.classList.add('hidden');
        state.isDropdownVisible = false;
        state.currentFocus = -1;
    }

    function setActiveItem(items) {
        removeActive(items);
        if (state.currentFocus >= items.length) state.currentFocus = 0;
        if (state.currentFocus < 0) state.currentFocus = items.length - 1;

        if (items[state.currentFocus]) {
            items[state.currentFocus].classList.add('active');
            items[state.currentFocus].scrollIntoView({ block: 'nearest' });
        }
    }

    function removeActive(items) {
        items.forEach(item => item.classList.remove('active'));
    }

    function addProduct(productName) {
        if (!productName || state.selectedProducts.has(productName)) return;
        state.selectedProducts.add(productName);
        renderSelectedProducts();
        updateActiveFilterCount();
    }

    function removeProduct(productName) {
        state.selectedProducts.delete(productName);
        renderSelectedProducts();
        updateActiveFilterCount();
    }

    function renderSelectedProducts() {
        elements.selectedProductsContainer.innerHTML = '';

        if (state.selectedProducts.size === 0) {
            elements.selectedProductsContainer.appendChild(elements.selectedProductsPlaceholder);
            elements.selectedProductsPlaceholder.classList.remove('hidden');
            return;
        }

        elements.selectedProductsPlaceholder.classList.add('hidden');
        state.selectedProducts.forEach(productName => {
            elements.selectedProductsContainer.appendChild(createProductTag(productName));
        });
    }

    function createProductTag(productName) {
        const tag = document.createElement('div');
        tag.className = 'receipts-filter-tag';

        const nameSpan = document.createElement('span');
        nameSpan.textContent = productName;

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'receipts-filter-tag-remove';
        removeBtn.setAttribute('aria-label', `Удалить ${productName}`);
        removeBtn.innerHTML = '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12"></path></svg>';
        removeBtn.addEventListener('click', () => removeProduct(productName));

        tag.appendChild(nameSpan);
        tag.appendChild(removeBtn);

        return tag;
    }

    function updateActiveFilterCount() {
        const badge = document.getElementById('receipts-filter-count');
        if (!badge) return;

        let count = 0;

        const dateInputs = document.querySelectorAll(
            '#receipts-filter-form input[name="receipt_date_0"], ' +
            '#receipts-filter-form input[name="receipt_date_1"]',
        );
        dateInputs.forEach(inp => { if (inp.value) count++; });

        const numberInputs = document.querySelectorAll('#receipts-filter-form input[type="number"]');
        numberInputs.forEach(inp => { if (inp.value) count++; });

        const selects = document.querySelectorAll('#receipts-filter-form select');
        selects.forEach(sel => { if (sel.value) count++; });

        count += state.selectedProducts.size;

        if (count > 0) {
            badge.textContent = count;
            badge.classList.remove('hidden');
        } else {
            badge.classList.add('hidden');
        }
    }

    function showSpinner() {
        if (elements.spinner) elements.spinner.classList.remove('hidden');
    }

    function hideSpinner() {
        if (elements.spinner) elements.spinner.classList.add('hidden');
    }

    function debounce(func, wait) {
        return function(...args) {
            clearTimeout(state.debounceTimer);
            state.debounceTimer = setTimeout(() => func(...args), wait);
        };
    }

    const ALLOWED_API_PATHS = ['/api/receipts/product-autocomplete/'];

    function isAllowedApiPath(pathname) {
        return ALLOWED_API_PATHS.some(allowed => pathname.startsWith(allowed));
    }

    async function fetchWithAuth(url, options = {}) {
        if (!url || typeof url !== 'string') throw new Error('Invalid URL');

        const urlObj = new URL(url, window.location.origin);
        if (urlObj.origin !== window.location.origin) throw new Error('URL must be same origin');
        if (!isAllowedApiPath(urlObj.pathname)) throw new Error('URL path not in allowed list');

        const safeUrl = `${urlObj.pathname}${urlObj.search}`;
        options.credentials = 'include';
        options.headers = options.headers || {};
        options.headers['X-Requested-With'] = 'XMLHttpRequest';

        let response = await fetch(safeUrl, options);

        if (response.status === 401) {
            const refreshResp = await fetch('/authentication/token/refresh/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
            });
            if (refreshResp.ok) return fetch(safeUrl, options);
        }

        return response;
    }

    window.ReceiptsFilter = {
        init,
        addProduct,
        removeProduct,
        getSelectedProducts: () => Array.from(state.selectedProducts),
        clearProducts: () => {
            state.selectedProducts.clear();
            renderSelectedProducts();
            updateActiveFilterCount();
        },
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
