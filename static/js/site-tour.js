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

    // Wait for driver.js to be available (it should be loaded via CDN or bundler)
    function initTourWhenReady(retryCount = 0) {
        console.log('[SiteTour] initTourWhenReady called, retry:', retryCount);
        
        // Try to access Driver from window object
        // The driver.js IIFE exports as window.driver.js (the function itself)
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
        console.log('[SiteTour] driverConstructor:', driverConstructor);

        // The IIFE returns an object with a 'driver' property containing the actual constructor
        const actualConstructor = driverConstructor.driver || driverConstructor;
        console.log('[SiteTour] actualConstructor type:', typeof actualConstructor);
        console.log('[SiteTour] actualConstructor:', actualConstructor);

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

        console.log('[SiteTour] driver instance methods:', Object.getOwnPropertyNames(Object.getPrototypeOf(driver)));
        console.log('[SiteTour] driver instance properties:', Object.keys(driver));

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

        // Define tour steps
        const tourSteps = [
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
                element: '#receipts',
                popover: {
                    title: 'Чеки',
                    description: 'Управление вашими чекам',
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
                    // Close dropdown when highlighting this element
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
                    // Open dropdown before showing this element
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
                    // Keep dropdown open
                    toggleFinanceDropdown(true);
                },
                onDeselected: () => {
                    // Close dropdown when moving to next step
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
                element: '#dashboard',
                popover: {
                    title: 'Дашборд',
                    description: 'Просмотр общей информации о ваших финансах',
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
                    // Close dropdown when highlighting this element
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
                    // Open dropdown before showing this element
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
                    // Keep dropdown open
                    toggleUserDropdown(true);
                },
                onDeselected: () => {
                    // Close dropdown when tour ends
                    toggleUserDropdown(false);
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
                    description: 'Здесь будет отображаться список всех групп, в которых вы состоите.\nСоздание группы происходит в настройках.\nПереключаться между группами по выбору из выпадающего списка',
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
        ];

        // Start the tour
        function startTour() {
            // Check if all required elements exist
            const missingElements = tourSteps.filter(step => !document.querySelector(step.element));
            
            if (missingElements.length > 0) {
                console.warn('[SiteTour] Some tour elements are missing:', missingElements.map(s => s.element));
                // Don't start tour if essential elements are missing
                if (missingElements.length === tourSteps.length) {
                    return;
                }
            }

            try {
                const validSteps = tourSteps.filter(step => document.querySelector(step.element));
                console.log('[SiteTour] Starting tour with', validSteps.length, 'steps');
                driver.setSteps(validSteps);
                driver.drive(0);
            } catch (error) {
                console.error('[SiteTour] Error starting tour:', error);
            }
        }

        // Check if user is visiting for the first time
        function isFirstVisit() {
            try {
                const visited = localStorage.getItem('siteTourCompleted');
                return !visited;
            } catch (error) {
                console.warn('[SiteTour] localStorage not available:', error);
                return false;
            }
        }

        // Mark tour as completed
        function markTourCompleted() {
            try {
                localStorage.setItem('siteTourCompleted', 'true');
            } catch (error) {
                console.warn('[SiteTour] Could not save to localStorage:', error);
            }
        }

        // Initialize tour
        function initTour() {
            if (isFirstVisit()) {
                // Show tour after content is loaded (increased to 2.5 seconds to ensure DOM is ready)
                setTimeout(() => {
                    startTour();
                }, 2500);
            }
        }

        // Note: driver.js doesn't have an 'on' method, so we'll mark tour as completed
        // when the user starts it or after the timeout
        console.log('[SiteTour] Tour initialized, starting initialization sequence');

        // Export functions for manual triggering (FIRST - before initTour)
        window.SiteTour = {
            start: startTour,
            restart: () => {
                console.log('[SiteTour] Restart called');
                try {
                    localStorage.removeItem('siteTourCompleted');
                } catch (error) {
                    console.warn('[SiteTour] Could not remove from localStorage:', error);
                }
                startTour();
            },
            markCompleted: markTourCompleted,
            driver: driver
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
