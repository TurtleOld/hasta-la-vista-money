from django.db import migrations


OLD_NAME = 'Cleanup stale pending receipts'
OLD_TASK = 'receipts.cleanup_stale_pending_receipts'
NEW_NAME = 'Cleanup stale receipt processing logs'
NEW_TASK = 'receipts.cleanup_stale_receipt_processing_logs'


def update_cleanup_task(apps, _schema_editor):
    periodic_model = apps.get_model('django_celery_beat', 'PeriodicTask')
    periodic_model.objects.filter(name=OLD_NAME, task=OLD_TASK).update(
        name=NEW_NAME,
        task=NEW_TASK,
    )


def restore_cleanup_task(apps, _schema_editor):
    periodic_model = apps.get_model('django_celery_beat', 'PeriodicTask')
    periodic_model.objects.filter(name=NEW_NAME, task=NEW_TASK).update(
        name=OLD_NAME,
        task=OLD_TASK,
    )


class Migration(migrations.Migration):
    dependencies = [
        ('django_celery_beat', '0019_alter_periodictasks_options'),
        ('receipts', '0020_seed_category_twin_periodic_task'),
    ]

    operations = [
        migrations.RunPython(update_cleanup_task, restore_cleanup_task),
        migrations.DeleteModel(name='PendingReceipt'),
    ]
