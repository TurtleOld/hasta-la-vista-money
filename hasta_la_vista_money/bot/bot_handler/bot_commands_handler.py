from hasta_la_vista_money import constants
from hasta_la_vista_money.account.models import Account
from hasta_la_vista_money.bot.bot_handler.auth_user_handler import handle_auth
from hasta_la_vista_money.bot.bot_handler.keyboards import (
    create_buttons_with_account,
)
from hasta_la_vista_money.bot.bot_handler.pin_message_handler import (
    pin_message,
)
from hasta_la_vista_money.bot.config_bot.config_bot import bot_admin
from hasta_la_vista_money.bot.middleware.middleware import AccessMiddleware
from hasta_la_vista_money.bot.receipt_handler.content_type_handler import (
    telegram_content_type,
)
from hasta_la_vista_money.bot.receipt_handler.receipt_parser import (
    SendMessageToTelegramUser,
)
from hasta_la_vista_money.bot.services import (
    check_account_exist,
    get_telegram_user,
)
from hasta_la_vista_money.users.models import TelegramUser

bot_admin.setup_middleware(AccessMiddleware())


@bot_admin.message_handler(commands=['start', 'help'])
def handle_start_help(message):
    """
    Функция обработчик команд start и help.

    :param message:
    :return:
    """
    SendMessageToTelegramUser.send_message_to_telegram_user(
        message.chat.id,
        constants.HELP_TEXT_START,
    )


@bot_admin.message_handler(commands=['auth'])
def handle_start(message):
    """
    Обработка команды /auth.

    :param message:
    :return:
    """
    telegram_user = get_telegram_user(message)
    if telegram_user:
        SendMessageToTelegramUser.send_message_to_telegram_user(
            message.chat.id,
            constants.ALREADY_LOGGED,
        )
    else:
        SendMessageToTelegramUser.send_message_to_telegram_user(
            message.chat.id,
            constants.REQUIRED_AUTHORIZATION,
        )
        bot_admin.register_next_step_handler(message, handle_auth)


@bot_admin.message_handler(commands=['select_account'])
def select_account(message):
    """
    Выбор счёта пользователем.

    :param message:
    :return:
    """
    telegram_user = get_telegram_user(message)
    user = telegram_user.user
    if check_account_exist(user):
        markup = create_buttons_with_account(user)
        bot_admin.reply_to(message, 'Выберете счёт:', reply_markup=markup)
    else:
        bot_admin.reply_to(message, 'У вас нет доступных счетов.')


@bot_admin.callback_query_handler(
    func=lambda call: call.data.startswith(
        'select_account_',
    ),
)
def handle_select_account(call):
    """
    Обработка выбора счёта пользователем.

    :param call:
    :return:
    """
    telegram_user = get_telegram_user(call)
    account_id = int(call.data.split('_')[2])
    telegram_user.selected_account_id = account_id
    telegram_user.save()
    account = Account.objects.filter(id=account_id).first()
    pin_message(call, account)


@bot_admin.message_handler(commands=['deauthorize'])
def process_deauthorize(message):
    """
    Функция отвязки телеграм аккаунта от аккаунта на сайте.

    :param message:
    :return:
    """
    TelegramUser.objects.get(telegram_id=message.from_user.id).delete()
    SendMessageToTelegramUser.send_message_to_telegram_user(
        message.chat.id,
        'Телеграм аккаунт отвязан!',
    )


@bot_admin.message_handler(content_types=['document', 'photo'])
def handle_receipt(message):
    """
    Проверка того, зарегистрированный ли пользователь пишет боту.

    :param message:
    :return:
    """
    telegram_user = get_telegram_user(message)
    if telegram_user:
        user = telegram_user.user
        account = telegram_user.selected_account_id
        telegram_content_type(message, user, account)


@bot_admin.message_handler(commands=['text'])
def handle_text_qr(message):
    """Start handler command text."""
    bot_admin.send_message(message.chat.id, 'Пришли текст из QR-кода')
    bot_admin.register_next_step_handler(message, handle_text)


def handle_text(message):
    """Handle text command from text QR-code."""
    telegram_user = get_telegram_user(message)
    if telegram_user:
        user = telegram_user.user
        account = telegram_user.selected_account_id
        telegram_content_type(message, user, account)
