import datetime
from typing import Final

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
SUCCESS_MESSAGE_CREATE_SELLER: Final = _(
    'Новый продавец успешно добавлен!',
)

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
HELP_TEXT_PASSWORD: Final = _(
    'Пароли хранятся в зашифрованном виде, '
    'поэтому нет возможности посмотреть ваш пароль, '
    'но вы можете сбросить пароль, выполнив команду '
    '<code>docker exec -it hlvm_server sh -c '
    '"python manage.py changepassword &lt;username&gt;"</code> '
    'в консоли сервера.',
)

HELP_TEXT_FORGOT_PASSWORD: Final = _(
    'Укажите логин, который указывали при регистрации.<br>'
    'Ссылка для восстановления пароля будет выслана в чат с ботом.<br>'
    'После нажатия на кнопку ниже, '
    'произойдёт переадресация в телеграм.',
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

# Числа
ONE: Final = 1
TWO: Final = 2
TEN: Final = 10
TWENTY: Final = 20
THIRTY: Final = 30
FORTY: Final = 40
FIFTY: Final = 50
SIXTY: Final = 60
SEVENTY: Final = 70
EIGHTY: Final = 80
NINTY: Final = 90
ONE_HUNDRED: Final = 100
ONE_HUNDRED_FIFTY: Final = 150
TWO_HUNDRED: Final = 200
TWO_HUNDRED_FIFTY: Final = 250
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
TODAY = datetime.datetime.today()
CURRENT_YEAR = datetime.date.today().year

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
