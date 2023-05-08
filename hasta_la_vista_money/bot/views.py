import json
import os
from typing import List

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from hasta_la_vista_money.bot.config_bot import bot_admin
from hasta_la_vista_money.bot.log_config import logger
from telebot import types, TeleBot

STATUS_SUCCESS = 200
STATUS_BAD = 500
token_bot = os.environ.get('TOKEN_TELEGRAM_BOT')


class MyBot(TeleBot):
    def process_new_updates(self, updates: List[types.Update]):
        try:
            if not updates:
                logger.error('Not Updates')
            logger.error(updates)
            super(MyBot, self).process_new_updates(updates)
        except Exception as error:
            logger.error(error)


my_bot = MyBot(token_bot)


@csrf_exempt
def webhooks(request):
    try:
        if request.method == 'POST':
            update = types.Update.de_json(
                json.loads(request.body.decode('utf8'))
            )
            my_bot.process_new_updates([update])
            return HttpResponse(
                'Webhook processed successfully', status=STATUS_SUCCESS,
            )
        return HttpResponse(
            'Webhook URL for Telegram bot', status=STATUS_SUCCESS,
            )
    except Exception as error:
        logger.error(error)



