from django.db import migrations

PERIODIC_TASK_NAME = 'users.cleanup_expired_bank_statements'
TASK_PATH = 'users.cleanup_expired_bank_statements'


def seed_cleanup_task(apps, _schema_editor):
    """Register the hourly bank statement retention task."""
    interval_model = apps.get_model('django_celery_beat', 'IntervalSchedule')
    periodic_model = apps.get_model('django_celery_beat', 'PeriodicTask')
    schedule, _created = interval_model.objects.get_or_create(
        every=1,
        period='hours',
    )
    periodic_model.objects.get_or_create(
        name=PERIODIC_TASK_NAME,
        defaults={
            'task': TASK_PATH,
            'interval': schedule,
            'enabled': True,
        },
    )


def remove_cleanup_task(apps, _schema_editor):
    """Remove the bank statement retention task on rollback."""
    periodic_model = apps.get_model('django_celery_beat', 'PeriodicTask')
    periodic_model.objects.filter(
        name=PERIODIC_TASK_NAME,
        task=TASK_PATH,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('users', '0015_bankstatementupload_expires_at_and_more'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(seed_cleanup_task, remove_cleanup_task),
    ]
