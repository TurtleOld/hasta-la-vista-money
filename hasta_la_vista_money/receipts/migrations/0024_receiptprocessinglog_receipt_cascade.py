import django.db.models.deletion
from django.db import migrations, models


def delete_orphaned_completed_logs(apps, schema_editor):
    # A completed entry whose receipt was deleted blocks rescanning it.
    apps.get_model('receipts', 'ReceiptProcessingLog').objects.filter(
        status='completed',
        receipt__isnull=True,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('receipts', '0023_alter_receiptprocessinglog_image_file'),
    ]

    operations = [
        migrations.AlterField(
            model_name='receiptprocessinglog',
            name='receipt',
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='processing_log',
                to='receipts.receipt',
            ),
        ),
        migrations.RunPython(
            delete_orphaned_completed_logs,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
