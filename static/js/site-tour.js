// Site Tour using driver.js
console.log('[SiteTour] File loaded');

(function() {
    console.log('[SiteTour] IIFE function called');
    'use strict';

    console.log('[SiteTour] Script initialized');
    console.log('[SiteTour] User authenticated:', typeof window.userIsAuthenticated !== 'undefined');

    // Create SiteTour object immediately
    window.SiteTour = window.SiteTour || {};

    // Check if user is authenticated (driver.js should only be available for authenticated users)
    if (typeof window.userIsAuthenticated === 'undefined') {
        // User is not authenticated, don't load tour
        console.log('[SiteTour] User not authenticated, skipping tour');
        return;
    }

    // Determine current page from URL
    function getCurrentPage() {
        const pathname = window.location.pathname;
        
        if (pathname.includes('/receipts')) {
            return 'receipts';
        } else if (pathname.includes('/expense')) {
            return 'expense';
        } else if (pathname.includes('/income')) {
            return 'income';
        } else if (pathname.includes('/budget')) {
            return 'budget';
        } else if (pathname.includes('/loan')) {
            return 'loan';
        } else if (pathname.includes('/reports')) {
            return 'reports';
        } else if (pathname.includes('/finance_account')) {
            return 'finance_account';
        }
        
        return 'unknown';
    }

    // Wait for driver.js to be available (it should be loaded via CDN or bundler)
    function initTourWhenReady(retryCount = 0) {
        console.log('[SiteTour] initTourWhenReady called, retry:', retryCount);
        
        // Try to access Driver from window object
        console.log('[SiteTour] window.driver available:', !!window.driver);
        if (window.driver) {
            console.log('[SiteTour] window.driver properties:', Object.keys(window.driver));
        }
        if (retryCount === 0) {
            console.log('[SiteTour] Checking for window.driver.js:', window.driver && window.driver.js);
        }
        
        const driverConstructor = window.driver && window.driver.js;
        
        if (!driverConstructor) {
            if (retryCount < 50) { // Max 50 retries = 5 seconds
                if (retryCount % 10 === 0) {
                    console.log('[SiteTour] Waiting for driver.js... (retry ' + (retryCount + 1) + ')');
                }
                setTimeout(() => initTourWhenReady(retryCount + 1), 100);
            } else {
                console.error('[SiteTour] driver.js failed to load after 5 seconds');
                console.error('[SiteTour] typeof window.driver:', typeof window.driver);
                console.error('[SiteTour] window.driver:', window.driver);
                if (window.driver) {
                    console.error('[SiteTour] Available properties in window.driver:', Object.keys(window.driver));
                }
            }
            return;
        }

        console.log('[SiteTour] driver.js loaded successfully');
        console.log('[SiteTour] driverConstructor type:', typeof driverConstructor);

        // The IIFE returns an object with a 'driver' property containing the actual constructor
        const actualConstructor = driverConstructor.driver || driverConstructor;
        console.log('[SiteTour] actualConstructor type:', typeof actualConstructor);

        // Initialize driver instance
        let driver;
        try {
            driver = new actualConstructor({
                allowClose: true,
                nextBtnText: 'Далее',
                prevBtnText: 'Назад',
                doneBtnText: 'Готово',
                showProgress: true,
                opacity: 0.75,
                padding: 10
            });
        } catch (error) {
            console.error('[SiteTour] Error creating driver instance:', error);
            return;
        }

        console.log('[SiteTour] driver instance created successfully');

        // Helper function to toggle dropdown menu
        function toggleFinanceDropdown(show = true) {
            const button = document.getElementById('financeDropdownButton');
            const menu = document.getElementById('financeDropdownMenu');
            const arrow = document.getElementById('financeDropdownArrow');
            
            if (!button || !menu || !arrow) return;
            
            if (show) {
                menu.classList.remove('hidden');
                button.setAttribute('aria-expanded', 'true');
                arrow.style.transform = 'rotate(180deg)';
            } else {
                menu.classList.add('hidden');
                button.setAttribute('aria-expanded', 'false');
                arrow.style.transform = 'rotate(0deg)';
            }
        }

        // Helper function to toggle user dropdown menu
        function toggleUserDropdown(show = true) {
            const button = document.getElementById('userDropdownButton');
            const menu = document.getElementById('userDropdownMenu');
            const arrow = document.getElementById('userDropdownArrow');

            if (!button || !menu || !arrow) return;

            if (show) {
                menu.classList.remove('hidden');
                button.setAttribute('aria-expanded', 'true');
                arrow.style.transform = 'rotate(180deg)';
            } else {
                menu.classList.add('hidden');
                button.setAttribute('aria-expanded', 'false');
                arrow.style.transform = 'rotate(0deg)';
            }
        }

        // Common navbar steps (shown on all pages)
        const commonNavbarSteps = [
            {
                element: '#navbar',
                popover: {
                    title: 'Навигация',
                    description: 'Используйте это меню для перемещения по сайту',
                    side: 'bottom',
                    align: 'start'
                }
            },
            {
                element: '#account-list',
                popover: {
                    title: 'Список счетов',
                    description: 'Нажатие на логотип возвращает на главную и список счетов',
                    side: 'bottom',
                    align: 'start'
                }
            },
            {
                element: '#financeDropdown',
                popover: {
                    title: 'Финансы',
                    description: 'Управление расходами и доходами. Нажмите далее для раскрытия меню.',
                    side: 'bottom',
                    align: 'start'
                },
                onHighlightStarted: () => {
                    toggleFinanceDropdown(false);
                }
            },
            {
                element: '#financeDropdownMenu li:nth-child(1) a',
                popover: {
                    title: 'Доходы',
                    description: 'Здесь вы можете управлять вашими доходами',
                    side: 'bottom',
                    align: 'start'
                },
                onHighlightStarted: () => {
                    toggleFinanceDropdown(true);
                }
            },
            {
                element: '#financeDropdownMenu li:nth-child(2) a',
                popover: {
                    title: 'Расходы',
                    description: 'Здесь вы можете управлять вашими расходами',
                    side: 'bottom',
                    align: 'start'
                },
                onHighlightStarted: () => {
                    toggleFinanceDropdown(true);
                },
                onDeselected: () => {
                    toggleFinanceDropdown(false);
                }
            },
            {
                element: '#budget',
                popover: {
                    title: 'Бюджет',
                    description: 'Здесь вы можете управлять вашим бюджетом',
                    side: 'bottom',
                    align: 'start'
                }
            },
            {
                element: '#loans',
                popover: {
                    title: 'Кредиты',
                    description: 'Здесь вы можете управлять вашими кредитами',
                    side: 'bottom',
                    align: 'start'
                }
            },
            {
                element: '#reports',
                popover: {
                    title: 'Отчеты',
                    description: 'Анализ ваших финансов с помощью отчетов',
                    side: 'bottom',
                    align: 'start'
                },
            },
            {
                element: '#user-menu',
                popover: {
                    title: 'Меню пользователя',
                    description: 'Управление вашим аккаунтом и выход',
                    side: 'bottom',
                    align: 'start'
                },
                onHighlightStarted: () => {
                    toggleUserDropdown(false);
                }
            },
            {
                element: '#userDropdownMenu li:nth-child(1) a',
                popover: {
                    title: 'Профиль',
                    description: 'Перейти в ваш профиль для изменения настроек',
                    side: 'left',
                    align: 'start'
                },
                onHighlightStarted: () => {
                    toggleUserDropdown(true);
                }
            },
            {
                element: '#userDropdownMenu li:nth-child(3) button',
                popover: {
                    title: 'Выход',
                    description: 'Выйти из вашего аккаунта',
                    side: 'left',
                    align: 'start'
                },
                onHighlightStarted: () => {
                    toggleUserDropdown(true);
                },
                onDeselected: () => {
                    toggleUserDropdown(false);
                }
            }
        ];

        // Page-specific tour steps
        const pageTours = {
            finance_account: [
                ...commonNavbarSteps,
                {
                    element: '#receipts',
                    popover: {
                        title: 'Чеки',
                        description: 'Управление вашими чеками',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: '#detailed-statistics',
                    popover: {
                        title: 'Детальная статистика',
                        description: 'Нажмите здесь для просмотра детальной статистики по доходам, расходам, чекам и переводам',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: '#finance-account-create',
                    popover: {
                        title: 'Добавить счет',
                        description: 'Нажмите здесь для создания нового финансового счета',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: '#transfer-money-between-accounts',
                    popover: {
                        title: 'Перевести средства',
                        description: 'Нажмите здесь для перевода средств между вашими счетами',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: '#group-accounts',
                    popover: {
                        title: 'Группа счетов',
                        description: 'Здесь будет отображаться список всех групп, в которых вы состоите.<br>Создание группы происходит в настройках.\nПереключаться между группами по выбору из выпадающего списка',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: '#balance-trend-widget',
                    popover: {
                        title: 'Тренд баланса',
                        description: 'Здесь отображается текущий баланс вашей группы счетов и тренд изменения баланса.<br><br>• <strong>Текущий баланс</strong> - общая сумма всех счетов<br>• <strong>Период (7 и 30 дней, 12 месяцев)</strong> - переключение периода анализа<br>• <strong>Изменение в ₽</strong> - абсолютное изменение за период<br>• <strong>Процент (%)</strong> - процентное изменение за период<br>• <strong>График</strong> - визуализация тренда баланса с цветовой кодировкой (зеленый - рост, красный - падение)',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: '#sum-all-groups-accounts',
                    popover: {
                        title: 'Сумма всех счетов со всех групп',
                        description: 'Здесь будет отображаться сумма всех счетов всех групп, в которых вы состоите',
                        side: 'bottom',
                        align: 'start'
                    }
                }
            ],
            receipts: [
                {
                    element: '#receipts',
                    popover: {
                        title: 'Чеки',
                        description: 'Вы находитесь на странице управления чеками',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: 'a[href*="/receipts/products/"]',
                    popover: {
                        title: 'Часто покупаемые товары',
                        description: 'Просмотрите список ваших часто покупаемых товаров',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: 'a[href*="/receipts/add-seller/"]',
                    popover: {
                        title: 'Добавить продавца',
                        description: 'Создайте новую запись о продавце',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: 'a[href*="/receipts/create/"]',
                    popover: {
                        title: 'Добавить чек',
                        description: 'Вручную добавьте новый чек в систему',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: 'a[href*="/receipts/upload/"]',
                    popover: {
                        title: 'Добавить чек из изображения',
                        description: 'Загрузите фотографию чека для автоматической обработки',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: '#receipt-group-select',
                    popover: {
                        title: 'Группа чеков',
                        description: 'Фильтруйте чеки по группам счетов',
                        side: 'bottom',
                        align: 'start'
                    }
                }
            ],
            expense: [
                ...commonNavbarSteps,
                {
                    element: '#financeDropdownMenu li:nth-child(2) a',
                    popover: {
                        title: 'Расходы',
                        description: 'Вы находитесь на странице управления расходами',
                        side: 'bottom',
                        align: 'start'
                    }
                }
            ],
            income: [
                ...commonNavbarSteps,
                {
                    element: '#financeDropdownMenu li:nth-child(1) a',
                    popover: {
                        title: 'Доходы',
                        description: 'Вы находитесь на странице управления доходами',
                        side: 'bottom',
                        align: 'start'
                    }
                }
            ],
            budget: [
                ...commonNavbarSteps,
                {
                    element: '#budget',
                    popover: {
                        title: 'Бюджет',
                        description: 'Вы находитесь на странице управления бюджетом',
                        side: 'bottom',
                        align: 'start'
                    }
                }
            ],
            loan: [
                ...commonNavbarSteps,
                {
                    element: '#loans',
                    popover: {
                        title: 'Кредиты',
                        description: 'Вы находитесь на странице управления кредитами и займами',
                        side: 'bottom',
                        align: 'start'
                    }
                }
            ],
            reports: [
                ...commonNavbarSteps,
                {
                    element: '#reports',
                    popover: {
                        title: 'Отчеты',
                        description: 'Вы находитесь на странице аналитики и отчетов',
                        side: 'bottom',
                        align: 'start'
                    }
                }
            ]
        };

        // Get current page
        const currentPage = getCurrentPage();
        console.log('[SiteTour] Current page:', currentPage);

        // Get tour steps for current page
        const tourSteps = pageTours[currentPage] || commonNavbarSteps;

        // Check if user is visiting page for the first time
        function isFirstVisitToPage() {
            try {
                const storageKey = `siteTourCompleted_${currentPage}`;
                const visited = localStorage.getItem(storageKey);
                console.log('[SiteTour] Storage key:', storageKey, 'Visited:', !!visited);
                return !visited;
            } catch (error) {
                console.warn('[SiteTour] localStorage not available:', error);
                return false;
            }
        }

        // Mark tour as completed for this page
        function markTourCompletedForPage() {
            try {
                const storageKey = `siteTourCompleted_${currentPage}`;
                localStorage.setItem(storageKey, 'true');
                console.log('[SiteTour] Marked tour as completed for page:', currentPage);
            } catch (error) {
                console.warn('[SiteTour] Could not save to localStorage:', error);
            }
        }

        // Start the tour
        function startTour() {
            // Check if all required elements exist
            const missingElements = tourSteps.filter(step => !document.querySelector(step.element));
            
            if (missingElements.length > 0) {
                console.warn('[SiteTour] Some tour elements are missing:', missingElements.map(s => s.element));
                // Don't start tour if essential elements are missing
                if (missingElements.length === tourSteps.length) {
                    console.warn('[SiteTour] All tour elements are missing, skipping tour');
                    return;
                }
            }

            try {
                const validSteps = tourSteps.filter(step => document.querySelector(step.element));
                console.log('[SiteTour] Starting tour for', currentPage, 'with', validSteps.length, 'steps');
                driver.setSteps(validSteps);
                driver.drive(0);
                markTourCompletedForPage();
            } catch (error) {
                console.error('[SiteTour] Error starting tour:', error);
            }
        }

        // Initialize tour
        function initTour() {
            if (isFirstVisitToPage()) {
                console.log('[SiteTour] First visit to page detected, scheduling tour start');
                // Show tour after content is loaded
                setTimeout(() => {
                    startTour();
                }, 2500);
            } else {
                console.log('[SiteTour] Page already visited, tour not starting automatically');
            }
        }

        console.log('[SiteTour] Tour initialization setup complete');

        // Export functions for manual triggering
        window.SiteTour = {
            start: startTour,
            restart: () => {
                console.log('[SiteTour] Restart called for page:', currentPage);
                try {
                    const storageKey = `siteTourCompleted_${currentPage}`;
                    localStorage.removeItem(storageKey);
                } catch (error) {
                    console.warn('[SiteTour] Could not remove from localStorage:', error);
                }
                startTour();
            },
            markCompleted: markTourCompletedForPage,
            restartAll: () => {
                console.log('[SiteTour] Restart all called - clearing all page tours');
                try {
                    const keysToRemove = [];
                    for (let i = 0; i < localStorage.length; i++) {
                        const key = localStorage.key(i);
                        if (key && key.startsWith('siteTourCompleted_')) {
                            keysToRemove.push(key);
                        }
                    }
                    keysToRemove.forEach(key => localStorage.removeItem(key));
                } catch (error) {
                    console.warn('[SiteTour] Could not clear localStorage:', error);
                }
            },
            driver: driver,
            currentPage: currentPage
        };
        console.log('[SiteTour] window.SiteTour methods exported');

        // Initialize on page load
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initTour);
        } else {
            // DOM is already loaded
            initTour();
        }
    }

    // Start initialization when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => initTourWhenReady(0));
    } else {
        initTourWhenReady(0);
    }
})();
