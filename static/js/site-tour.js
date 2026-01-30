// Site Tour using driver.js
(function() {
    'use strict';

    // Create SiteTour object immediately
    window.SiteTour = window.SiteTour || {};

    // Check if user is authenticated (driver.js should only be available for authenticated users)
    if (typeof window.userIsAuthenticated === 'undefined') {
        // User is not authenticated, don't load tour
        return;
    }

        // Determine current page from URL
        // Valid page names for security validation
        const VALID_PAGES = new Set([
            'receipts',
            'budget_expense',
            'budget_income',
            'budget',
            'expense',
            'income',
            'loan',
            'reports',
            'finance_account'
        ]);

        function getCurrentPage() {
            const pathname = window.location.pathname;
            
            if (pathname.includes('/receipts')) {
                return 'receipts';
            } else if (pathname.includes('/expense') && pathname.includes('/budget')) {
                return 'budget_expense';
            } else if (pathname.includes('/income') && pathname.includes('/budget')) {
                return 'budget_income';
            } else if (pathname.includes('/budget')) {
                return 'budget';
            } else if (pathname.includes('/expense')) {
                return 'expense';
            } else if (pathname.includes('/income')) {
                return 'income';
            } else if (pathname.includes('/loan')) {
                return 'loan';
            } else if (pathname.includes('/reports')) {
                return 'reports';
            } else if (pathname.includes('/finance_account')) {
                return 'finance_account';
            }
            
            return 'unknown';
        }

        // Validate page name to prevent object injection attacks
        function isValidPage(pageName) {
            return VALID_PAGES.has(pageName);
        }

    // Wait for driver.js to be available (it should be loaded via CDN or bundler)
    function initTourWhenReady(retryCount = 0) {
        const driverConstructor = window.driver && window.driver.js;
        
        if (!driverConstructor) {
            if (retryCount < 50) { // Max 50 retries = 5 seconds
                setTimeout(() => initTourWhenReady(retryCount + 1), 100);
            }
            return;
        }

        // The IIFE returns an object with a 'driver' property containing the actual constructor
        const actualConstructor = driverConstructor.driver || driverConstructor;

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

        // Helper function to toggle receipt filter
        function toggleReceiptFilter(show = true) {
            const filterCollapse = document.getElementById('filterCollapse');
            const filterToggle = document.getElementById('filterToggle');
            const filterToggleIcon = document.getElementById('filterToggleIcon');

            if (!filterCollapse || !filterToggle || !filterToggleIcon) return;

            if (show) {
                filterCollapse.classList.remove('hidden');
                filterToggle.setAttribute('aria-expanded', 'true');
                filterToggleIcon.classList.add('rotate-180');
            } else {
                filterCollapse.classList.add('hidden');
                filterToggle.setAttribute('aria-expanded', 'false');
                filterToggleIcon.classList.remove('rotate-180');
            }
        }

        // Common navbar steps (shown only on finance_account page)
        const financeAccountNavbarSteps = [
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
                ...financeAccountNavbarSteps,
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
                    element: '#filterToggle',
                    popover: {
                        title: 'Фильтр чеков',
                        description: 'Нажмите здесь для раскрытия фильтра. Фильтр позволяет вам:<br>• Фильтровать чеки по периоду<br>• Задавать диапазон сумм<br>• Выбирать продавца<br>• Искать товары в чеках',
                        side: 'bottom',
                        align: 'start'
                    },
                    onHighlightStarted: () => {
                        toggleReceiptFilter(true);
                    },
                    onDeselected: () => {
                        toggleReceiptFilter(false);
                    }
                },
                {
                    element: 'a[href*="/receipts/products"]',
                    popover: {
                        title: 'Часто покупаемые товары',
                        description: 'Просмотрите список ваших часто покупаемых товаров',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: 'a[href*="/receipts/create_seller/"]',
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
                {
                    element: '#toggle-group-filter',
                    popover: {
                        title: 'Фильтр по группе',
                        description: 'Нажмите здесь для раскрытия фильтра по группе. Это позволит вам просматривать расходы для разных групп счетов.',
                        side: 'bottom',
                        align: 'end'
                    }
                },
                {
                    element: 'a[href*="/expense/create"]',
                    popover: {
                        title: 'Добавить расход',
                        description: 'Нажмите здесь для создания нового расхода',
                        side: 'bottom',
                        align: 'end'
                    }
                },
                {
                    element: 'a[href*="/expense/category"]',
                    popover: {
                        title: 'Управление категориями',
                        description: 'Нажмите здесь для управления категориями расходов',
                        side: 'bottom',
                        align: 'end'
                    }
                },
                {
                    element: '.expense-table',
                    popover: {
                        title: 'Таблица расходов',
                        description: 'Здесь отображается список всех ваших расходов с информацией о сумме, дате, категории и счете.<br><br>Вы можете сортировать и фильтровать данные используя заголовки колонок.<br><br><strong>Важно:</strong> В таблице также отображаются чеки.',
                        side: 'top',
                        align: 'start'
                    }
                }
            ],
            income: [
                {
                    element: '#toggle-group-filter',
                    popover: {
                        title: 'Фильтр по группе',
                        description: 'Нажмите здесь для раскрытия фильтра по группе. Это позволит вам просматривать доходы для разных групп счетов.',
                        side: 'bottom',
                        align: 'end'
                    }
                },
                {
                    element: 'a[href*="/income/create"]',
                    popover: {
                        title: 'Добавить доход',
                        description: 'Нажмите здесь для создания нового дохода',
                        side: 'bottom',
                        align: 'end'
                    }
                },
                {
                    element: 'a[href*="/income/category"]',
                    popover: {
                        title: 'Управление категориями',
                        description: 'Нажмите здесь для управления категориями доходов',
                        side: 'bottom',
                        align: 'end'
                    }
                },
                {
                    element: '.income-table',
                    popover: {
                        title: 'Таблица доходов',
                        description: 'Здесь отображается список всех ваших доходов с информацией о сумме, дате, категории и счете. Вы можете сортировать и фильтровать данные используя заголовки колонок.',
                        side: 'top',
                        align: 'start'
                    }
                }
            ],
            budget: [
                {
                    element: '#budget-expense-table-btn',
                    popover: {
                        title: 'Таблица расходов',
                        description: 'Нажмите здесь для просмотра таблицы всех расходов по категориям и месяцам. Вы сможете увидеть план и фактические расходы, а также управлять планированием.',
                        side: 'bottom',
                        align: 'start'
                    },
                    onNextClick: () => {
                        // Переход в таблицу расходов
                        const btn = document.querySelector('#budget-expense-table-btn');
                        if (btn) {
                            setTimeout(() => {
                                btn.click();
                                setTimeout(() => {
                                    // Ждем загрузки страницы
                                    if (window.SiteTour && window.SiteTour.driver) {
                                        window.SiteTour.driver.drive(1);
                                    }
                                }, 1500);
                            }, 100);
                        }
                    }
                },
                {
                    element: '#expense-budget-table',
                    popover: {
                        title: 'Таблица расходов',
                        description: 'Здесь вы видите таблицу с планируемыми и фактическими расходами.<br><br><strong>Структура таблицы:</strong><br>• Каждая строка - это категория расходов<br>• Каждая колонка - это месяц<br>• Слева план (Plan), справа фактические расходы (Fact)<br><br>Вы можете редактировать плановые значения прямо в таблице, кликнув по нужной ячейке.',
                        side: 'top',
                        align: 'start'
                    },
                    onNextClick: () => {
                        // Переход назад на главную бюджета
                        const backBtn = document.querySelector('a[href*="/budget"]:first-of-type');
                        if (backBtn) {
                            setTimeout(() => {
                                backBtn.click();
                                setTimeout(() => {
                                    if (window.SiteTour && window.SiteTour.driver) {
                                        window.SiteTour.driver.drive(2);
                                    }
                                }, 1500);
                            }, 100);
                        }
                    }
                },
                {
                    element: '#budget-income-table-btn',
                    popover: {
                        title: 'Таблица доходов',
                        description: 'Нажмите здесь для просмотра таблицы всех доходов по категориям и месяцам. Аналогично таблице расходов, вы можете планировать и отслеживать доходы.',
                        side: 'bottom',
                        align: 'start'
                    },
                    onNextClick: () => {
                        // Переход в таблицу доходов
                        const btn = document.querySelector('#budget-income-table-btn');
                        if (btn) {
                            setTimeout(() => {
                                btn.click();
                                setTimeout(() => {
                                    if (window.SiteTour && window.SiteTour.driver) {
                                        window.SiteTour.driver.drive(3);
                                    }
                                }, 1500);
                            }, 100);
                        }
                    }
                },
                {
                    element: '#income-budget-table',
                    popover: {
                        title: 'Таблица доходов',
                        description: 'Здесь отображается таблица с планируемыми и фактическими доходами.<br><br><strong>Структура таблицы:</strong><br>• Каждая строка - это категория дохода<br>• Каждая колонка - это месяц<br>• Слева план (Plan), справа фактические доходы (Fact)<br><br>Вы можете редактировать плановые значения доходов, кликнув по нужной ячейке.',
                        side: 'top',
                        align: 'start'
                    },
                    onNextClick: () => {
                        // Переход назад на главную бюджета
                        const backBtn = document.querySelector('a[href*="/budget"]:first-of-type');
                        if (backBtn) {
                            setTimeout(() => {
                                backBtn.click();
                                setTimeout(() => {
                                    if (window.SiteTour && window.SiteTour.driver) {
                                        window.SiteTour.driver.drive(4);
                                    }
                                }, 1500);
                            }, 100);
                        }
                    }
                },
                {
                    element: '#budget-reports-btn',
                    popover: {
                        title: 'Отчёты',
                        description: 'Здесь вы можете переходить к разделу отчетов для более детального анализа ваших доходов и расходов с различными диаграммами и статистикой.',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: '#budget-add-months-btn',
                    popover: {
                        title: 'Добавить ещё месяцы',
                        description: 'Нажмите эту кнопку для добавления новых месяцев к вашему плану бюджета. Это позволит вам планировать расходы и доходы на более длительный период.',
                        side: 'bottom',
                        align: 'start'
                    }
                }
            ],
            budget_expense: [
                {
                    element: '#expense-budget-table',
                    popover: {
                        title: 'Таблица расходов',
                        description: 'Здесь вы видите таблицу с планируемыми и фактическими расходами.<br><br><strong>Структура таблицы:</strong><br>• <strong>Строки</strong> - категории расходов<br>• <strong>Колонки</strong> - месяцы<br>• <strong>Слева (Plan)</strong> - плановые расходы<br>• <strong>Справа (Fact)</strong> - фактические расходы<br><br><strong>Редактирование:</strong> Кликните по ячейке плана, чтобы отредактировать плановое значение. Система автоматически сохранит изменения.',
                        side: 'top',
                        align: 'start'
                    }
                }
            ],
            budget_income: [
                {
                    element: '#income-budget-table',
                    popover: {
                        title: 'Таблица доходов',
                        description: 'Здесь отображается таблица с планируемыми и фактическими доходами.<br><br><strong>Структура таблицы:</strong><br>• <strong>Строки</strong> - категории доходов<br>• <strong>Колонки</strong> - месяцы<br>• <strong>Слева (Plan)</strong> - плановые доходы<br>• <strong>Справа (Fact)</strong> - фактические доходы<br><br><strong>Редактирование:</strong> Кликните по ячейке плана, чтобы отредактировать плановое значение. Система автоматически сохранит изменения.',
                        side: 'top',
                        align: 'start'
                    }
                }
            ],
            loan: [
                {
                    element: 'a[href*="/loan/create"]',
                    popover: {
                        title: 'Добавить кредит',
                        description: 'Нажмите здесь для создания нового кредита. Вы сможете указать сумму, ставку и срок кредита.',
                        side: 'bottom',
                        align: 'start'
                    }
                },
                {
                    element: 'details.group',
                    popover: {
                        title: 'Подсказка по расчетам',
                        description: 'Раскройте этот раздел для получения информации о расчетах кредитов. Здесь содержатся формулы для расчета аннуитетных платежей и прочие справочные данные.',
                        side: 'bottom',
                        align: 'start'
                    },
                    onHighlightStarted: () => {
                        const details = document.querySelector('details.group');
                        if (details) {
                            details.open = true;
                        }
                    },
                    onDeselected: () => {
                        const details = document.querySelector('details.group');
                        if (details) {
                            details.open = false;
                        }
                    }
                },
                {
                    element: '#loans-list',
                    popover: {
                        title: 'Список кредитов',
                        description: 'Здесь отображаются все ваши кредиты в виде карточек.<br><br><strong>Каждая карточка показывает:</strong><br>• Номер и тип кредита<br>• Сумму, ставку и срок<br>• Общую сумму к возврату<br>• Размер переплаты<br><br><strong>Действия:</strong> Нажмите кнопку "График" для просмотра расписания платежей или "Платеж" для внесения платежа',
                        side: 'top',
                        align: 'start'
                    }
                }
            ],
            reports: [
            ]
        };

        // Get current page
        const currentPage = getCurrentPage();
        console.log('[SiteTour] Current page:', currentPage);

        // Validate page name to prevent generic object injection attacks
        // Use only if it's in our whitelist (VALID_PAGES)
        const validatedPage = isValidPage(currentPage) ? currentPage : 'unknown';
        
        // Get tour steps for current page (safely access with validated key)
        const tourSteps = (validatedPage !== 'unknown' && pageTours[validatedPage]) ? pageTours[validatedPage] : [];

        // Check if tour is globally disabled
        function isTourGloballyDisabled() {
            try {
                const disabled = localStorage.getItem('siteTourGloballyDisabled');
                console.log('[SiteTour] Tour globally disabled:', !!disabled);
                return !!disabled;
            } catch (error) {
                console.warn('[SiteTour] localStorage not available:', error);
                return false;
            }
        }

        // Mark tour as globally disabled
        function disableTourGlobally() {
            try {
                localStorage.setItem('siteTourGloballyDisabled', 'true');
                console.log('[SiteTour] Tour disabled globally');
            } catch (error) {
                console.warn('[SiteTour] Could not save to localStorage:', error);
            }
        }

        // Enable tour globally
        function enableTourGlobally() {
            try {
                localStorage.removeItem('siteTourGloballyDisabled');
                console.log('[SiteTour] Tour enabled globally');
            } catch (error) {
                console.warn('[SiteTour] Could not access localStorage:', error);
            }
        }

        // Helper function to create checkbox HTML for popover
        function createDontShowCheckboxHtml() {
            const checkboxHtml = `
                <div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #ddd;">
                    <label style="display: flex; align-items: center; font-size: 14px; margin: 0; cursor: pointer;">
                        <input type="checkbox" id="siteTourDontShowCheckbox" 
                               style="margin-right: 8px; cursor: pointer; width: 16px; height: 16px;">
                        <span>Больше не показывать</span>
                    </label>
                </div>
            `;
            return checkboxHtml;
        }

        // Override the popover description to add checkbox to last step
        function enhancePopoverWithCheckbox(steps) {
            if (steps.length === 0) return steps;
            
            // Clone the steps to avoid mutating original
            const enhancedSteps = steps.map((step, index) => {
                const newStep = { ...step };
                
                // Add checkbox HTML to the last step
                if (index === steps.length - 1) {
                    const originalDesc = newStep.popover.description || '';
                    const descriptionWithHtml = originalDesc + createDontShowCheckboxHtml();
                    newStep.popover.description = descriptionWithHtml;
                    
                    // Add callback to handle checkbox change
                    const originalOnHighlightStarted = newStep.onHighlightStarted;
                    newStep.onHighlightStarted = () => {
                        if (originalOnHighlightStarted) {
                            originalOnHighlightStarted();
                        }
                        
                        // Set up checkbox listener after a short delay to ensure it's in DOM
                        setTimeout(() => {
                            const checkbox = document.getElementById('siteTourDontShowCheckbox');
                            if (checkbox) {
                                checkbox.addEventListener('change', () => {
                                    if (checkbox.checked) {
                                        console.log('[SiteTour] User disabled tour globally');
                                        disableTourGlobally();
                                    }
                                });
                            }
                        }, 100);
                    };
                }
                
                return newStep;
            });
            
            return enhancedSteps;
        }

        // Start the tour
        function startTour() {
            // Check if tour is globally disabled
            if (isTourGloballyDisabled()) {
                console.log('[SiteTour] Tour is globally disabled, skipping');
                return;
            }

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
                const enhancedSteps = enhancePopoverWithCheckbox(validSteps);
                
                console.log('[SiteTour] Starting tour for', currentPage, 'with', enhancedSteps.length, 'steps');
                driver.setSteps(enhancedSteps);
                driver.drive(0);
            } catch (error) {
                console.error('[SiteTour] Error starting tour:', error);
            }
        }

        // Initialize tour - show on every page load (unless globally disabled)
        function initTour() {
            if (isTourGloballyDisabled()) {
                console.log('[SiteTour] Tour is globally disabled, not starting');
                return;
            }

            console.log('[SiteTour] Tour is enabled, scheduling tour start');
            // Show tour after content is loaded
            setTimeout(() => {
                startTour();
            }, 2500);
        }

        console.log('[SiteTour] Tour initialization setup complete');

        // Export functions for manual triggering
        window.SiteTour = {
            start: startTour,
            restart: () => {
                console.log('[SiteTour] Restart called for page:', validatedPage);
                startTour();
            },
            enableTour: () => {
                console.log('[SiteTour] Enable tour called');
                enableTourGlobally();
                startTour();
            },
            disableTour: () => {
                console.log('[SiteTour] Disable tour called');
                disableTourGlobally();
            },
            restartAll: () => {
                console.log('[SiteTour] Restart all called - clearing global disable flag');
                try {
                    enableTourGlobally();
                } catch (error) {
                    console.warn('[SiteTour] Could not clear localStorage:', error);
                }
                startTour();
            },
            driver: driver,
            currentPage: validatedPage
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
