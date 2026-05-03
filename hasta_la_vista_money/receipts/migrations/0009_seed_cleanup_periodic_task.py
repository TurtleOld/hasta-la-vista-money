from django.db import migrations

PERIODIC_TASK_NAME = 'Cleanup stale pending receipts'
TASK_PATH = 'receipts.cleanup_stale_pending_receipts'
INTERVAL_EVERY = 1
INTERVAL_PERIOD = 'hours'


def seed_cleanup_task(apps, schema_editor):
    """Register an hourly periodic task for stale-pending cleanup."""
    interval_model = apps.get_model('django_celery_beat', 'IntervalSchedule')
    periodic_model = apps.get_model('django_celery_beat', 'PeriodicTask')

    schedule, _created = interval_model.objects.get_or_create(
        every=INTERVAL_EVERY,
        period=INTERVAL_PERIOD,
    )
    periodic_model.objects.update_or_create(
        name=PERIODIC_TASK_NAME,
        defaults={
            'task': TASK_PATH,
            'interval': schedule,
            'enabled': True,
        },
    )


def remove_cleanup_task(apps, schema_editor):
    """Remove the periodic task on rollback; leave the schedule for reuse."""
    periodic_model = apps.get_model('django_celery_beat', 'PeriodicTask')
    periodic_model.objects.filter(name=PERIODIC_TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('receipts', '0008_add_pending_processing_and_image_hash'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(seed_cleanup_task, remove_cleanup_task),
    ]
