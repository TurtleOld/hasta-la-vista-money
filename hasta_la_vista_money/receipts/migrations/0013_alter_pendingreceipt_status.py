from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('receipts', '0012_add_receipt_search_indexes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pendingreceipt',
            name='status',
            field=models.CharField(
                choices=[
                    ('processing', 'В обработке'),
                    ('ready', 'Готов к проверке'),
                    ('ready_with_warning', 'Готов с предупреждением'),
                    ('failed', 'Ошибка обработки'),
                ],
                default='processing',
                max_length=20,
                verbose_name='Статус',
            ),
        ),
    ]
