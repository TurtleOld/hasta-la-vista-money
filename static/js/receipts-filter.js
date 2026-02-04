/* eslint-env browser */
/**
 * Receipt Filter Module
 * Модуль для управления фильтром чеков с автодополнением и множественным выбором товаров
 */

(function() {
    'use strict';

    // Состояние модуля
    const state = {
        selectedProducts: new Set(),
        autocompleteResults: [],
        currentFocus: -1,
        debounceTimer: null,
        isDropdownVisible: false
    };

    // DOM элементы
    const elements = {
        productInput: null,
        selectedProductsContainer: null,
        selectedProductsPlaceholder: null,
        autocompleteDropdown: null,
        selectedProductsInput: null,
        spinner: null,
        filterForm: null,
        productInputWrapper: null
    };

    /**
     * Инициализация модуля
     */
    function init() {
        // Инициализируем переключатель фильтра
        initFilterCollapse();

        // Получаем DOM элементы для автодополнения
        elements.productInput = document.getElementById('product-autocomplete');
        elements.selectedProductsContainer = document.getElementById('selected-products-container');
        elements.selectedProductsPlaceholder = document.getElementById('selected-products-placeholder');
        elements.autocompleteDropdown = document.getElementById('product-autocomplete-dropdown');
        elements.selectedProductsInput = document.getElementById('selected-products-input');
        elements.spinner = document.getElementById('product-input-spinner');
        elements.filterForm = document.getElementById('receipts-filter-form');

        if (!elements.productInput) return;

        // Находим контейнер для позиционирования dropdown
        elements.productInputWrapper = elements.productInput.parentElement;

        // Загружаем выбранные товары из URL параметров
        loadSelectedProductsFromUrl();

        // Добавляем обработчики событий
        attachEventListeners();
    }

    /**
     * Инициализация переключателя фильтра
     */
    function initFilterCollapse() {
        const filterCollapse = document.getElementById('filterCollapse');
        const toggleButton = document.getElementById('filterToggle');
        const toggleIcon = document.getElementById('filterToggleIcon');

        if (!filterCollapse || !toggleButton || !toggleIcon) {
            return;
        }

        function updateIcon(isExpanded) {
            toggleIcon.classList.toggle('rotate-180', Boolean(isExpanded));
        }

        function toggleCollapse() {
            const isExpanded = !filterCollapse.classList.contains('hidden');

            if (isExpanded) {
                filterCollapse.classList.add('hidden');
                toggleButton.setAttribute('aria-expanded', 'false');
                updateIcon(false);
            } else {
                filterCollapse.classList.remove('hidden');
                toggleButton.setAttribute('aria-expanded', 'true');
                updateIcon(true);
            }
        }

        if (window.location.search.length > 1) {
            filterCollapse.classList.remove('hidden');
            toggleButton.setAttribute('aria-expanded', 'true');
            updateIcon(true);
        }

        toggleButton.addEventListener('click', function(e) {
            e.preventDefault();
            toggleCollapse();
        });
    }

    /**
     * Загрузка выбранных товаров из URL параметров
     */
    function loadSelectedProductsFromUrl() {
        const urlParams = new URLSearchParams(window.location.search);
        const productNames = urlParams.get('product_names');

        if (productNames) {
            try {
                const decoded = decodeURIComponent(productNames);
                const products = decoded.split(',').map(p => p.trim()).filter(p => p);
                products.forEach(product => {
                    state.selectedProducts.add(product);
                });
                renderSelectedProducts();
            } catch (e) {
                console.error('Error loading products from URL:', e);
            }
        }
    }

    /**
     * Добавление обработчиков событий
     */
    function attachEventListeners() {
        // Ввод текста в поле поиска с debounce
        elements.productInput.addEventListener('input', debounce(handleInput, 300));

        // Навигация с клавиатуры
        elements.productInput.addEventListener('keydown', handleKeydown);

        // Потеря фокуса
        elements.productInput.addEventListener('blur', handleBlur);

        // Получение фокуса
        elements.productInput.addEventListener('focus', handleFocus);

        // Клик вне dropdown
        document.addEventListener('click', handleDocumentClick);

        // Отправка формы
        if (elements.filterForm) {
            elements.filterForm.addEventListener('submit', handleFormSubmit);
        }
    }

    /**
     * Обработка ввода текста
     */
    async function handleInput() {
        const query = elements.productInput.value.trim();

        // Скрываем спиннер
        hideSpinner();

        if (query.length === 0) {
            hideDropdown();
            return;
        }

        // Показываем спиннер
        showSpinner();

        try {
            const response = await fetchWithAuth(`/api/receipts/product-autocomplete/?q=${encodeURIComponent(query)}`);
            hideSpinner();

            if (!response.ok) {
                hideDropdown();
                return;
            }

            const data = await response.json();
            state.autocompleteResults = (data.results || []).filter(
                product => !state.selectedProducts.has(product)
            );

            showDropdown();
        } catch (e) {
            hideSpinner();
            hideDropdown();
            console.error('Error fetching autocomplete:', e);
        }
    }

    /**
     * Обработка нажатий клавиш
     */
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
                // Добавляем введенный текст как товар
                addProduct(elements.productInput.value.trim());
                elements.productInput.value = '';
                hideDropdown();
            }
        } else if (e.key === 'Escape') {
            hideDropdown();
        } else if (e.key === 'Backspace' && elements.productInput.value === '' && state.selectedProducts.size > 0) {
            // Удаляем последний выбранный товар
            const lastProduct = Array.from(state.selectedProducts).pop();
            removeProduct(lastProduct);
        }
    }

    /**
     * Обработка потери фокуса
     */
    function handleBlur() {
        // Задержка перед скрытием dropdown, чтобы успеть обработать клик
        setTimeout(() => {
            hideDropdown();
        }, 200);
    }

    /**
     * Обработка получения фокуса
     */
    function handleFocus() {
        if (elements.productInput.value.trim()) {
            handleInput();
        }
    }

    /**
     * Обработка клика вне dropdown
     */
    function handleDocumentClick(e) {
        if (!elements.productInput.contains(e.target) &&
            !elements.autocompleteDropdown.contains(e.target)) {
            hideDropdown();
        }
    }

    /**
     * Обработка отправки формы
     */
    function handleFormSubmit() {
        // Обновляем скрытое поле с выбранными товарами
        elements.selectedProductsInput.value = Array.from(state.selectedProducts).join(',');
    }

    /**
     * Отображение dropdown с результатами
     */
    function showDropdown() {
        if (!state.autocompleteResults.length) {
            hideDropdown();
            return;
        }

        elements.autocompleteDropdown.innerHTML = '';

        state.autocompleteResults.forEach((product, index) => {
            const item = document.createElement('div');
            item.className = 'autocomplete-item px-4 py-2.5 text-sm text-gray-700 dark:text-gray-300 cursor-pointer hover:bg-green-50 dark:hover:bg-green-900/20 transition-colors duration-150';
            item.textContent = product;
            item.dataset.index = index;

            item.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                addProduct(product);
                elements.productInput.value = '';
                hideDropdown();
                elements.productInput.focus();
            });

            elements.autocompleteDropdown.appendChild(item);
        });

        // Позиционируем dropdown относительно viewport (fixed), чтобы не обрезался родительскими контейнерами
        // Это гарантирует, что dropdown будет отображаться поверх всех элементов независимо от прокрутки
        const wrapperRect = elements.productInputWrapper.getBoundingClientRect();

        // Вычисляем margin-top из класса mt-1 (0.25rem) для точного позиционирования
        // Используем getComputedStyle для получения актуального значения margin
        const dropdownComputedStyle = window.getComputedStyle(elements.autocompleteDropdown);
        const marginTop = parseFloat(dropdownComputedStyle.marginTop) || 4; // mt-1 = 0.25rem ≈ 4px

        // Устанавливаем точное позиционирование относительно viewport
        elements.autocompleteDropdown.style.position = 'fixed';
        // Левая граница строго соответствует левой границе обертки инпута
        elements.autocompleteDropdown.style.left = `${wrapperRect.left}px`;
        // Верхняя граница = нижняя граница обертки + margin-top для идеального выравнивания
        elements.autocompleteDropdown.style.top = `${wrapperRect.bottom + marginTop}px`;
        // Ширина строго соответствует ширине обертки инпута
        elements.autocompleteDropdown.style.width = `${wrapperRect.width}px`;

        elements.autocompleteDropdown.classList.remove('hidden');
        state.isDropdownVisible = true;
        state.currentFocus = -1;
    }

    /**
     * Скрытие dropdown
     */
    function hideDropdown() {
        elements.autocompleteDropdown.classList.add('hidden');
        state.isDropdownVisible = false;
        state.currentFocus = -1;
    }

    /**
     * Установка активного элемента при навигации клавиатурой
     */
    function setActiveItem(items) {
        removeActive(items);

        if (state.currentFocus >= items.length) state.currentFocus = 0;
        if (state.currentFocus < 0) state.currentFocus = items.length - 1;

        if (items[state.currentFocus]) {
            items[state.currentFocus].classList.add('active', 'bg-green-100', 'dark:bg-green-900/30');
            items[state.currentFocus].scrollIntoView({ block: 'nearest' });
        }
    }

    /**
     * Удаление активного класса
     */
    function removeActive(items) {
        items.forEach(item => {
            item.classList.remove('active', 'bg-green-100', 'dark:bg-green-900/30');
        });
    }

    /**
     * Добавление товара в список выбранных
     */
    function addProduct(productName) {
        if (!productName || state.selectedProducts.has(productName)) return;

        state.selectedProducts.add(productName);
        renderSelectedProducts();
    }

    /**
     * Удаление товара из списка выбранных
     */
    function removeProduct(productName) {
        state.selectedProducts.delete(productName);
        renderSelectedProducts();
    }

    /**
     * Отображение выбранных товаров в виде тегов
     */
    function renderSelectedProducts() {
        // Очищаем контейнер
        elements.selectedProductsContainer.innerHTML = '';

        if (state.selectedProducts.size === 0) {
            // Показываем placeholder
            elements.selectedProductsContainer.appendChild(elements.selectedProductsPlaceholder);
            elements.selectedProductsPlaceholder.classList.remove('hidden');
            return;
        }

        // Скрываем placeholder
        elements.selectedProductsPlaceholder.classList.add('hidden');

        // Добавляем теги для каждого товара
        state.selectedProducts.forEach(productName => {
            const tag = createProductTag(productName);
            elements.selectedProductsContainer.appendChild(tag);
        });
    }

    /**
     * Создание тега товара
     */
    function createProductTag(productName) {
        const tag = document.createElement('div');
        tag.className = 'inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-green-700 dark:text-green-400 bg-green-100 dark:bg-green-900/30 border border-green-200 dark:border-green-800 rounded-full transition-all duration-200 hover:bg-green-200 dark:hover:bg-green-900/50 group';

        const nameSpan = document.createElement('span');
        nameSpan.textContent = productName;
        nameSpan.className = 'max-w-[200px] truncate';

        const removeButton = document.createElement('button');
        removeButton.type = 'button';
        removeButton.className = 'flex items-center justify-center w-4 h-4 text-green-600 dark:text-green-500 hover:text-green-800 dark:hover:text-green-300 transition-colors duration-150';
        removeButton.innerHTML = `
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
        `;
        removeButton.setAttribute('aria-label', `Удалить ${productName}`);
        removeButton.addEventListener('click', () => removeProduct(productName));

        tag.appendChild(nameSpan);
        tag.appendChild(removeButton);

        return tag;
    }

    /**
     * Показать спиннер загрузки
     */
    function showSpinner() {
        if (elements.spinner) {
            elements.spinner.classList.remove('hidden');
        }
    }

    /**
     * Скрыть спиннер загрузки
     */
    function hideSpinner() {
        if (elements.spinner) {
            elements.spinner.classList.add('hidden');
        }
    }

    /**
     * Debounce функция
     */
    function debounce(func, wait) {
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(state.debounceTimer);
                func(...args);
            };
            clearTimeout(state.debounceTimer);
            state.debounceTimer = setTimeout(later, wait);
        };
    }

    /**
     * Fetch с авторизацией
     */
    async function fetchWithAuth(url, options = {}) {
        if (!url || typeof url !== 'string') {
            throw new Error('Invalid URL provided');
        }

        try {
            const urlObj = new URL(url, window.location.origin);
            if (urlObj.origin !== window.location.origin) {
                throw new Error('URL must be from same origin');
            }

            options.credentials = 'include';
            options.headers = options.headers || {};
            options.headers['X-Requested-With'] = 'XMLHttpRequest';

            let response = await fetch(url, options);

            // Обработка 401 - попытка обновить токен
            if (response.status === 401) {
                const refreshResp = await fetch('/authentication/token/refresh/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include'
                });

                if (refreshResp.ok) {
                    return fetch(url, options);
                }
            }

            return response;
        } catch (e) {
            console.error('Fetch error:', e);
            throw e;
        }
    }

    // Экспорт функций для использования в других модулях
    window.ReceiptsFilter = {
        init,
        addProduct,
        removeProduct,
        getSelectedProducts: () => Array.from(state.selectedProducts),
        clearProducts: () => {
            state.selectedProducts.clear();
            renderSelectedProducts();
        }
    };

    // Инициализация при загрузке DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
