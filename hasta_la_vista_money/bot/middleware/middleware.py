from hasta_la_vista_money import constants
from hasta_la_vista_money.bot.send_message.send_message_tg_user import (
    SendMessageToTelegramUser,
)
from hasta_la_vista_money.users.models import TelegramUser
from telebot.handler_backends import BaseMiddleware, SkipHandler


class AccessMiddleware(BaseMiddleware):
    def __init__(self):
        """Конструктов класса инициализирующий аргументы класса."""
        super().__init__()
        self.telegram_username = None
        self.update_types = ['message']

    def pre_process(self, message, data):
        self.telegram_username = TelegramUser.objects.filter(
            telegram_id=message.from_user.id,
        ).first()
        if message.text and (
            '/auth' in message.text
            or '/start' in message.text
            or '/help' in message.text
        ):
            return None

        if self.telegram_username is None and message.text:
            SendMessageToTelegramUser.send_message_to_telegram_user(
                message.chat.id,
                constants.ACCESS_DENIED,
            )
            return SkipHandler()

    def post_process(self, message, data, exception):
        data['exception'] = exception
