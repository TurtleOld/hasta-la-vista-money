"""Celery configuration for async task processing."""

import logging
import os

from celery import Celery
from decouple import config

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.django.base')

app = Celery('hasta_la_vista_money')

# Configure Celery using settings from Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Use Redis as broker and result backend
# Use database 1 for Celery to avoid conflicts with cache (db 0)
redis_base = config('REDIS_LOCATION', default='redis://localhost:6379')
if redis_base.endswith(('/0', '/1')):
    redis_base = redis_base.rsplit('/', 1)[0]

app.conf.broker_url = f'{redis_base}/1'
app.conf.result_backend = f'{redis_base}/1'

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()

# Celery configuration
app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes max
    task_soft_time_limit=25 * 60,  # 25 minutes soft limit
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    # Use unique queue name for this project
    task_default_queue='hlvm_tasks',
    task_default_exchange='hlvm_tasks',
    task_default_routing_key='hlvm_tasks',
)


@app.task(bind=True, ignore_result=True)
def debug_task(self: Celery) -> None:
    """Debug task for testing Celery setup."""
    logging.getLogger(__name__).info('Request: %r', self.request)
