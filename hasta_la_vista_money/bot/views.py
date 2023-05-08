import json

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from hasta_la_vista_money.bot.config_bot import bot_admin, bot_type
from hasta_la_vista_money.bot.log_config import logger


@csrf_exempt
def webhooks(request):
    if request.method == 'POST':
        try:
            json_data = json.loads(request.body)
            updates = bot_type.Update.de_json(json_data)
            bot_admin.process_new_updates([json_data])
            return HttpResponse('Webhook processed successfully', status=200)
        except Exception as error:
            logger.error(error)
            return HttpResponse(status=500)
    else:
        return HttpResponse('Webhook URL for Telegram bot', status=200)
