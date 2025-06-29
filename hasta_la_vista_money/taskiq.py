import os

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_aio_pika import AioPikaBroker

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.django.base')

# Create broker instance with RabbitMQ
broker = AioPikaBroker(
    url=os.getenv('TASKIQ_RABBITMQ_URL', 'amqp://guest:guest@localhost:5672/'),
    task_default_queue='default',
    result_backend_url=os.getenv(
        'TASKIQ_RABBITMQ_URL',
        'amqp://guest:guest@localhost:5672/',
    ),
)

# Create scheduler for periodic tasks with LabelScheduleSource
scheduler = TaskiqScheduler(
    broker=broker,
    sources=[LabelScheduleSource(broker)],
)
