from django.shortcuts import get_object_or_404
from hasta_la_vista_money import constants
from hasta_la_vista_money.account.models import Account
from hasta_la_vista_money.bot.send_message.send_message_tg_user import (
    SendMessageToTelegramUser,
)
from hasta_la_vista_money.users.models import User


def get_string_result_receipt(**kwargs) -> str:
    """
    Формирование строки с краткой информацией о добавленном чеке.

    :param kwargs: Принимает несколько именованных аргументов.
    :return:
    """
    account_balance = get_object_or_404(Account, id=kwargs.get('account'))
    products = [
        product.product_name for product in kwargs.get('product_list', [])
    ]
    newline_char = '\n'
    return ''.join(
        (
            'Чек успешно добавлен.\n\n',
            'Параметры чека:\n',
            f'<b>Счёт списания:</b> {account_balance.name_account}\n',
            f'<b>Дата чека:</b> {kwargs.get("receipt_date")}\n',
            f'<b>Сумма чека:</b> {kwargs.get("total_sum")}\n',
            f'<b>Продавец:</b> {kwargs.get("customer")}\n\n',
            f"<b>Товары:</b>\n{f', {newline_char}'.join(products)}\n",
        ),
    )


def check_exists_number_receipt(user, receipt_date, number_receipt, total_sum):
    """
    Проверка на существование номера чека в базе данных.

    :param user:
    :param receipt_date:
    :param number_receipt:
    :param total_sum:
    :return:
    """
    user = get_object_or_404(User, username=user)
    return (
        user.receipt_users.select_related('user')
        .filter(
            receipt_date=receipt_date,
            number_receipt=number_receipt,
            total_sum=total_sum,
        )
        .first()
    )


def check_operation_type(operation_type, total_sum):
    """
    Проверка на тип операции.

    Если это возврат покупки или возврат выигрыша, то это минус со счёта.

    :param operation_type:
    :param total_sum:
    :return:
    """
    return -total_sum if operation_type in {2, 3} else total_sum


def handle_integrity_error(chat_id, integrity_error):
    """
    Обработка исключений.

    :param chat_id:
    :param integrity_error:
    :return:
    """
    if 'account' in str(integrity_error):
        SendMessageToTelegramUser.send_message_to_telegram_user(
            chat_id,
            constants.NOT_CREATE_ACCOUNT,
        )
    else:
        SendMessageToTelegramUser.send_message_to_telegram_user(
            chat_id,
            constants.ERROR_DATABASE_RECORD,
        )
