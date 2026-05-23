"""Replace ``category_expense`` / ``category_income`` on Planning with a
single ``category`` FK pointing at ``transactions.Category``.

The database is known to be empty at this point in the refactor, so no
data migration is required. The new column is added as nullable first
and then made NOT NULL in the same migration so makemigrations doesn't
ask for a one-off default.
"""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0006_planning_planning_category_matches_type'),
        ('transactions', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='planning',
            name='planning_category_matches_type',
        ),
        migrations.RemoveConstraint(
            model_name='planning',
            name='unique_planning_per_user_category_date_type',
        ),
        migrations.RemoveField(
            model_name='planning',
            name='category_expense',
        ),
        migrations.RemoveField(
            model_name='planning',
            name='category_income',
        ),
        migrations.AddField(
            model_name='planning',
            name='category',
            field=models.ForeignKey(
                help_text='Категория операции',
                null=True,
                on_delete=models.CASCADE,
                related_name='plannings',
                to='transactions.category',
                verbose_name='Категория',
            ),
        ),
        migrations.AlterField(
            model_name='planning',
            name='category',
            field=models.ForeignKey(
                help_text='Категория операции',
                on_delete=models.CASCADE,
                related_name='plannings',
                to='transactions.category',
                verbose_name='Категория',
            ),
        ),
        migrations.AlterField(
            model_name='planning',
            name='planning_type',
            field=models.CharField(
                choices=[
                    ('income', 'Доход'),
                    ('expense', 'Расход'),
                ],
                db_index=True,
                default='expense',
                help_text='Тип планирования: расход или доход',
                max_length=10,
                verbose_name='Тип',
            ),
        ),
        migrations.AddConstraint(
            model_name='planning',
            constraint=models.UniqueConstraint(
                fields=('user', 'category', 'date', 'planning_type'),
                name='unique_planning_per_user_category_date_type',
            ),
        ),
    ]
