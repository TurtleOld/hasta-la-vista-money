from typing import Final

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# Константы для парсинга json чека
NAME_SELLER: Final = 'user'
RETAIL_PLACE_ADDRESS: Final = 'retailPlaceAddress'
RETAIL_PLACE: Final = 'retailPlace'
RECEIPT_DATE_TIME: Final = 'dateTime'
NUMBER_RECEIPT: Final = 'fiscalDocumentNumber'
NUMBER_RECEIPT_ID: Final = 'documentId'
OPERATION_TYPE: Final = 'operationType'
TOTAL_SUM: Final = 'totalSum'
PRODUCT_NAME: Final = 'name'
PRICE: Final = 'price'
QUANTITY: Final = 'quantity'
AMOUNT: Final = 'sum'
NDS_TYPE: Final = 'nds'
NDS_SUM: Final = 'ndsSum'
NDS10: Final = 'nds10'
NDS20: Final = 'nds18'
ITEMS_PRODUCT: Final = 'items'

# Константы строк для парсинга чека
RECEIPT_ALREADY_EXISTS: Final = 'Такой чек уже существует!'
RECEIPT_BE_ADDED: Final = 'Чек успешно добавлен!'
RECEIPT_CANNOT_BE_ADDED: Final[tuple[str]] = (
    'Чек не корректен, перепроверьте в приложении налоговой!',
)
SUCCESS_MESSAGE_UPDATE_RECEIPT: Final = _('Чек успешно обновлен!')
RECEIPT_NOT_ACCEPTED: Final[tuple[str]] = (
    'Чек не прошёл валидацию! '
    'Вероятно он ещё не попал в базу данных налоговой! '
    'Обычно чек попадает в базу не позже суток. '
    'Попробуйте позже или внесите данные вручную на сайте.',
)
QR_CODE_NOT_CONSIDERED: Final[tuple[str]] = (
    'QR-код не считался, попробуйте ещё раз или воспользуйтесь '
    'сторонним приложением и передайте текст из QR-кода боту',
)

# Сообщения для сайта
SUCCESS_MESSAGE_LOGIN: Final = _('Вы успешно авторизовались!')
SUCCESS_MESSAGE_REGISTRATION: Final = _('Регистрация прошла успешно!')
SUCCESS_MESSAGE_CREATE_RECEIPT: Final = _('Чек успешно добавлен!')
SUCCESS_MESSAGE_DELETE_RECEIPT: Final = _('Чек успешно удален!')
SUCCESS_MESSAGE_CREATE_SELLER: Final = _(
    'Новый продавец успешно добавлен!',
)
INVALID_FILE_FORMAT: Final = _('Неверный формат файла или пустые данные')
ERROR_PROCESSING_RECEIPT: Final = _('Ошибка обработки чека, попробуйте позже')

# Шаблоны
EXPENSE_CATEGORY_TEMPLATE: Final = 'expense/show_category_expense.html'
EXPENSE_TEMPLATE: Final = 'expense/show_expense.html'

# URL names
EXPENSE_CATEGORY_LIST_URL: Final = 'expense:category_list'
EXPENSE_LIST_URL: Final = 'expense:list'

ANOTHER_ACCRUAL_ACCOUNT: Final = _(
    'Нельзя выбирать одинаковые счета для перевода.',
)
SUCCESS_MESSAGE_ADDED_ACCOUNT: Final = _('Счёт успешно создан!')
SUCCESS_MESSAGE_CHANGED_ACCOUNT: Final = _('Счёт успешно изменён!')
SUCCESS_MESSAGE_DELETE_ACCOUNT: Final = _('Счёт успешно удалён!')
UNSUCCESSFULLY_MESSAGE_DELETE_ACCOUNT: Final = _(
    'Счёт не может быть удалён!',
)
SUCCESS_MESSAGE_CHANGED_PROFILE: Final = _('Профиль успешно обновлён!')
SUCCESS_MESSAGE_CHANGED_PASSWORD: Final = _(
    'Новый пароль успешно установлен!',
)
SUCCESS_MESSAGE_LOGOUT: Final = _(
    'Вы успешно вышли из своей учётной записи!',
)

SUCCESS_CATEGORY_ADDED: Final = _('Категория добавлена!')
SUCCESS_EXPENSE_ADDED: Final = _('Операция расхода успешно добавлена!')
SUCCESS_INCOME_ADDED: Final = _('Операция дохода успешно добавлена!')
SUCCESS_INCOME_UPDATE: Final = _('Операция дохода успешно обновлена!')
SUCCESS_EXPENSE_UPDATE: Final = _('Операция расхода успешно обновлена!')
SUCCESS_EXPENSE_DELETED: Final = _('Операция расхода успешно удалена!')
SUCCESS_INCOME_DELETED: Final = _('Операция дохода успешно удалена!')
SUCCESS_CATEGORY_EXPENSE_DELETED: Final = _(
    'Категория расхода успешно удалена!',
)
SUCCESS_CATEGORY_INCOME_DELETED: Final = _(
    'Категория дохода успешно удалена!',
)
ACCESS_DENIED_DELETE_EXPENSE_CATEGORY: Final = _(
    'Категория не может быть удалена, так как связана с расходом',
)
ACCESS_DENIED_DELETE_INCOME_CATEGORY: Final = _(
    'Категория не может быть удалена, так как связана с доходом',
)
USER_MUST_BE_AUTHENTICATED: Final = _('Пользователь должен быть авторизован')
SUCCESS_MESSAGE_TRANSFER_MONEY: Final = _('Средства успешно переведены')
SUCCESS_MESSAGE_INSUFFICIENT_FUNDS: Final = _('Недостаточно средств')
SUCCESS_MESSAGE_LOAN_CREATE: Final = _('Кредит успешно добавлен')
SUCCESS_MESSAGE_LOAN_DELETE: Final = _('Кредит успешно удалён')
SUCCESS_MESSAGE_PAYMENT_MAKE: Final = _('Платеж успешно внесён')
ACCOUNT_FORM_NOTES: Final = _(
    'Введите заметку не более 250 символов. Поле необязательное!',
)

# HTTP Status
SUCCESS_CODE: Final = 200
SERVER_ERROR: Final = 500
NOT_FOUND: Final = 404
REDIRECTS: Final = 302

# Типы операций чеков
RECEIPT_OPERATION_PURCHASE: Final = 1
RECEIPT_OPERATION_RETURN: Final = 2

# Типы счетов
ACCOUNT_TYPE_CREDIT: Final = 'Credit'
ACCOUNT_TYPE_CREDIT_CARD: Final = 'CreditCard'

# Названия категорий
RECEIPT_CATEGORY_NAME: Final = 'Покупки по чекам'

# Числа
ZERO: Final = 0
ONE: Final = 1
TWO: Final = 2
THREE: Final = 3
FIVE: Final = 5
SIX: Final = 6
SAVINGS_THRESHOLD: Final = 0.2
TEN: Final = 10
TWELVE: Final = 12
TWENTY: Final = 20
THIRTY: Final = 30
THIRTY_TWO: Final = 32
FORTY: Final = 40
FIFTY: Final = 50
SIXTY: Final = 60
SEVENTY: Final = 70
EIGHTY: Final = 80
NINTY: Final = 90
ONE_HUNDRED: Final = 100
ONE_HUNDRED_TEN: Final = 110
ONE_HUNDRED_FIFTY: Final = 150
TWO_HUNDRED: Final = 200
TWO_HUNDRED_FIFTY: Final = 250
LOW_BALANCE_THRESHOLD: Final = 1000
DAY_MINUS_HOUR: Final = 23
MINUTE_MINUS_ONE: Final = 59
SECOND_MINUS_ONE: Final = 59
TODAY_MINUS_FIVE_YEARS: Final = 23
THREE_HUNDRED_SIXTY_FIVE: Final = 365

# Порядковые номера месяцев
NUMBER_FIRST_MONTH_YEAR: Final = 1
NUMBER_SECOND_MONTH_YEAR: Final = 2
NUMBER_THIRD_MONTH_YEAR: Final = 3
NUMBER_FOURTH_MONTH_YEAR: Final = 4
NUMBER_FIFTH_MONTH_YEAR: Final = 5
NUMBER_SIXTH_MONTH_YEAR: Final = 6
NUMBER_SEVENTH_MONTH_YEAR: Final = 7
NUMBER_EIGHTH_MONTH_YEAR: Final = 8
NUMBER_NINTH_MONTH_YEAR: Final = 9
NUMBER_TENTH_MONTH_YEAR: Final = 10
NUMBER_ELEVENTH_MONTH_YEAR: Final = 11
NUMBER_TWELFTH_MONTH_YEAR: Final = 12

# Настройки Cookies
SESSION_COOKIE_AGE: Final = 31536000

# Текст для ответов запросов
SUCCESS_WEBHOOKS: Final = 'Webhook processed successfully'
WEBHOOKS_TELEGRAM: Final = 'This page for Webhooks Telegram!'

# Параметры дат
TODAY = timezone.now().date()
CURRENT_YEAR = timezone.now().year

# Константы для тестов кредитов
TEST_LOAN_AMOUNT_SMALL: Final = 1000
TEST_LOAN_AMOUNT_MEDIUM: Final = 10000
TEST_LOAN_AMOUNT_LARGE: Final = 100000
TEST_INTEREST_RATE_LOW: Final = 5.0
TEST_INTEREST_RATE_MEDIUM: Final = 5.5
TEST_INTEREST_RATE_HIGH: Final = 12.0
TEST_INTEREST_RATE_EXTRA_HIGH: Final = 12.5
TEST_PERIOD_SHORT: Final = 1
TEST_PERIOD_MEDIUM: Final = 6
TEST_PERIOD_LONG: Final = 12
TEST_ACCOUNT_BALANCE: Final = 5000
TEST_PAYMENT_AMOUNT: Final = 1000
TEST_PAYMENT_INTEREST: Final = 100
TEST_PAYMENT_PRINCIPAL: Final = 900
TEST_PAYMENT_BALANCE: Final = 9000

# Константы для проверки точности расчётов
TOLERANCE_SMALL: Final = 0.01
TOLERANCE_MEDIUM: Final = 0.1
DECIMAL_PLACES_PRECISION: Final = 2
DECIMAL_PLACES_ROUNDING: Final = 1

# Константы для форм и полей ввода
QUANTITY_STEP: Final = 0.01
MAX_DIGITS_DECIMAL_FIELD: Final = 10
FORMSET_EXTRA_DEFAULT: Final = 1

# Константы для файлов
MAX_FILE_SIZE_MB: Final = 5
BYTES_IN_KB: Final = 1024
KB_IN_MB: Final = 1024
MAX_FILE_SIZE_BYTES: Final = MAX_FILE_SIZE_MB * KB_IN_MB * BYTES_IN_KB

# Константы для кредитов и процентов
PERCENT_TO_DECIMAL: Final = 100
MONTHS_IN_YEAR: Final = 12
GRACE_PERIOD_MONTHS_SBERBANK: Final = 3
GRACE_PERIOD_DAYS_RAIFFEISENBANK: Final = 110
STATEMENT_DAY_NUMBER: Final = 2
MIN_PAYMENT_PERCENTAGE: Final = 0.03
PAYMENT_DUE_DAYS: Final = 20
ONE_SECOND: Final = 1
STATEMENT_DATES_COUNT: Final = 3

# Константы для пагинации и лимитов
RECENT_ITEMS_LIMIT: Final = 5
PAGINATE_BY_DEFAULT: Final = 10
TOP_CATEGORIES_LIMIT: Final = 10
RECEIPTS_DISTINCT_LIMIT: Final = 10
TRANSFER_MONEY_LOG_LIMIT: Final = 10
RECEIPT_RANK_LIMIT: Final = 10
RECENT_RECEIPTS_LIMIT: Final = 20
TRANSFER_LOG_LIMIT: Final = 20

# Константы для статистики
STATISTICS_MONTHS_COUNT: Final = 6
STATISTICS_YEAR_MONTHS_COUNT: Final = 12
DAYS_IN_MONTH_APPROXIMATE: Final = 30
DAYS_FOR_NEXT_MONTH_CALC: Final = 32

# Константы для AI
AI_TEMPERATURE: Final = 0.6
NDS_RATE_10_PERCENT: Final = 10
NDS_RATE_20_PERCENT: Final = 20

# Константы для процентов
PERCENTAGE_MULTIPLIER: Final = 100

# Константы для известных значений расчётов
ANNUITY_MONTHLY_PAYMENT_100K_12M: Final = 8884.88
ANNUITY_TOTAL_PAYMENT_100K_12M: Final = 106618.53
ANNUITY_OVERPAYMENT_100K_12M: Final = 6618.53
ANNUITY_FIRST_PAYMENT_100K_12M: Final = 8884.88
ANNUITY_FIRST_INTEREST_100K_12M: Final = 1000.0
ANNUITY_FIRST_PRINCIPAL_100K_12M: Final = 7884.88

DIFF_PRINCIPAL_PAYMENT_100K_12M: Final = 8333.33
DIFF_FIRST_INTEREST_100K_12M: Final = 1000.0
DIFF_FIRST_PAYMENT_100K_12M: Final = 9333.33
DIFF_LAST_INTEREST_100K_12M: Final = 83.33
DIFF_LAST_PAYMENT_100K_12M: Final = 8416.67

# Константы для тестовых дат
TEST_DATE_STRING: Final = '2023-10-01'

MONTH_NUMBERS: Final = {
    'Январь': 1,
    'Февраль': 2,
    'Март': 3,
    'Апрель': 4,
    'Май': 5,
    'Июнь': 6,
    'Июль': 7,
    'Август': 8,
    'Сентябрь': 9,
    'Октябрь': 10,
    'Ноябрь': 11,
    'Декабрь': 12,
}

MONTH_NAMES: Final = {
    1: 'Январь',
    2: 'Февраль',
    3: 'Март',
    4: 'Апрель',
    5: 'Май',
    6: 'Июнь',
    7: 'Июль',
    8: 'Август',
    9: 'Сентябрь',
    10: 'Октябрь',
    11: 'Ноябрь',
    12: 'Декабрь',
}
