# Документация Site Tour (site-tour.js)

## Описание

Скрипт `site-tour.js` реализует интерактивные туры по разным страницам приложения с использованием библиотеки Driver.js.

## Как это работает

### Обнаружение страницы

Скрипт автоматически определяет текущую страницу на основе URL pathname:
- `/finance_account` → Тур для управления счетами
- `/receipts` → Тур для чеков
- `/expense` → Тур для расходов
- `/income` → Тур для доходов
- `/budget` → Тур для бюджета
- `/loan` → Тур для кредитов
- `/reports` → Тур для отчетов

### Отслеживание посещений

Каждая страница имеет свой ключ в `localStorage`:
```
siteTourCompleted_finance_account
siteTourCompleted_receipts
siteTourCompleted_expense
и т.д.
```

Тур автоматически показывается только при **первом посещении** конкретной страницы.

### Общие шаги (Common Steps)

На всех страницах показываются следующие элементы навигации:
- Навигационная панель (#navbar)
- Логотип/Список счетов (#account-list)
- Меню "Финансы" с подменю
- Меню "Бюджет", "Кредиты", "Отчеты"
- Меню пользователя

После этого показываются специфичные для каждой страницы элементы.

## Специфичные туры

### Finance Account (/finance_account)

Основная страница приложения. Тур показывает:
1. Навигационные элементы (общие)
2. Чеки (ссылка на /receipts)
3. Детальная статистика
4. Кнопка добавления счета
5. Кнопка перевода средств
6. Выбор группы счетов
7. Виджет тренда баланса
8. Сумма всех счетов

### Receipts (/receipts)

Страница управления чеками. Тур показывает:
1. Навигационные элементы (общие)
2. Название страницы (Чеки)
3. Часто покупаемые товары
4. Добавить продавца
5. Добавить чек (вручную)
6. Добавить чек из изображения
7. Фильтр по группам чеков

### Другие страницы

Для страниц expense, income, budget, loan, reports показываются:
1. Навигационные элементы (общие)
2. Пункт меню текущей страницы

## API для управления туром

### window.SiteTour.start()
Запустить тур текущей страницы вручную.

```javascript
window.SiteTour.start();
```

### window.SiteTour.restart()
Перезапустить тур текущей страницы (удаляет флаг посещения и показывает тур снова).

```javascript
window.SiteTour.restart();
```

### window.SiteTour.restartAll()
Очистить флаги посещения для **всех** страниц (полный сброс).

```javascript
window.SiteTour.restartAll();
```

### window.SiteTour.markCompleted()
Отметить текущую страницу как посещенную (скроет тур при следующем посещении).

```javascript
window.SiteTour.markCompleted();
```

### window.SiteTour.currentPage
Получить название текущей страницы.

```javascript
console.log(window.SiteTour.currentPage); // 'receipts', 'finance_account', и т.д.
```

### window.SiteTour.driver
Доступ к объекту Driver.js для расширенного использования.

```javascript
window.SiteTour.driver.moveNext();
window.SiteTour.driver.movePrev();
```

## Логирование

Скрипт выводит подробные логи в консоль браузера:
- `[SiteTour]` - префикс всех сообщений

Включает информацию о:
- Загрузке скрипта
- Определении текущей страницы
- Загрузке Driver.js
- Старте тура
- Сохранении флагов в localStorage

## Примеры использования

### Добавить кнопку "Показать тур" в навигацию

```html
<button onclick="window.SiteTour.restart()" class="btn btn-info">
  Показать тур
</button>
```

### Добавить кнопку сброса всех туров в профиль

```html
<button onclick="window.SiteTour.restartAll()" class="btn btn-warning">
  Сбросить все туры
</button>
```

### Проверить, была ли текущая страница посещена

```javascript
const isFirstVisit = !localStorage.getItem(`siteTourCompleted_${window.SiteTour.currentPage}`);
if (isFirstVisit) {
    console.log('Первое посещение страницы');
} else {
    console.log('Страница уже посещалась');
}
```

## Добавление новой страницы в тур

1. Добавьте новую страницу в функцию `getCurrentPage()`:

```javascript
function getCurrentPage() {
    const pathname = window.location.pathname;
    
    // ... существующие проверки ...
    
    if (pathname.includes('/my-new-page')) {
        return 'my_new_page';
    }
    
    return 'unknown';
}
```

2. Добавьте новый тур в объект `pageTours`:

```javascript
const pageTours = {
    // ... существующие туры ...
    
    my_new_page: [
        ...commonNavbarSteps,
        {
            element: '#my-element',
            popover: {
                title: 'Название',
                description: 'Описание',
                side: 'bottom',
                align: 'start'
            }
        }
    ]
};
```

## Требования

- **Driver.js** - должен быть загружен перед этим скриптом
- **Аутентификация** - скрипт проверяет наличие `window.userIsAuthenticated`
- **localStorage** - используется для сохранения флагов посещения

## Отладка

Если тур не показывается:

1. Проверьте консоль браузера на наличие ошибок
2. Убедитесь, что `window.userIsAuthenticated` определен
3. Проверьте, что Driver.js загружен (см. логи `[SiteTour]`)
4. Проверьте localStorage:
   ```javascript
   localStorage.getItem(`siteTourCompleted_${window.SiteTour.currentPage}`);
   ```
5. Очистите флаг и перезагрузите страницу:
   ```javascript
   window.SiteTour.restart();
   ```

## История изменений

### v2.0 (текущая версия)
- ✅ Разные туры для разных страниц
- ✅ Независимое отслеживание посещений per-page
- ✅ Удобный API для управления турами
- ✅ Поддержка 7 различных страниц
- ✅ Подробное логирование

### v1.0
- Единый тур для всей страницы Finance Account
