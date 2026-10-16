from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0004_transaction_description'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='system_kind',
            field=models.CharField(
                blank=True,
                choices=[('balance_adjustment', 'Корректировка остатка')],
                default='',
                max_length=32,
            ),
        ),
        migrations.AddConstraint(
            model_name='category',
            constraint=models.UniqueConstraint(
                condition=models.Q(('system_kind', ''), _negated=True),
                fields=('user', 'system_kind', 'type'),
                name='unique_user_system_category_kind_per_type',
            ),
        ),
    ]
