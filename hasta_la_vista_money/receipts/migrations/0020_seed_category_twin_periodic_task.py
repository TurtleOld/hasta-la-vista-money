from django.db import migrations

PERIODIC_TASK_NAME = 'Find twin product categories'
TASK_PATH = 'receipts.find_category_merge_proposals'
INTERVAL_EVERY = 1
INTERVAL_PERIOD = 'days'


def seed_twin_task(apps, schema_editor):
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


def remove_twin_task(apps, schema_editor):
    periodic_model = apps.get_model('django_celery_beat', 'PeriodicTask')
    periodic_model.objects.filter(name=PERIODIC_TASK_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('receipts', '0019_categorymergeproposal'),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
    ]

    operations = [
        migrations.RunPython(seed_twin_task, remove_twin_task),
    ]
