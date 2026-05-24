import datetime
import decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ('budget', '0001_squashed'),
        ('transactions', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Budget',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'period',
                    models.DateField(
                        db_index=True,
                        default=datetime.date.today,
                        help_text='Первый день месяца, на который задан лимит',
                        verbose_name='Период',
                    ),
                ),
                (
                    'amount_limit',
                    models.DecimalField(
                        decimal_places=2,
                        default=0,
                        help_text='Максимальная сумма расходов за период',
                        max_digits=12,
                        validators=[
                            django.core.validators.MinValueValidator(
                                decimal.Decimal('0'),
                            ),
                        ],
                        verbose_name='Лимит',
                    ),
                ),
                (
                    'alert_threshold',
                    models.PositiveSmallIntegerField(
                        default=80,
                        help_text=(
                            'Процент использования лимита для предупреждения'
                        ),
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(100),
                        ],
                        verbose_name='Порог предупреждения',
                    ),
                ),
                (
                    'created_at',
                    models.DateTimeField(
                        auto_now_add=True,
                        blank=True,
                        null=True,
                        verbose_name='Дата создания',
                    ),
                ),
                (
                    'updated_at',
                    models.DateTimeField(
                        auto_now=True,
                        blank=True,
                        null=True,
                        verbose_name='Дата обновления',
                    ),
                ),
                (
                    'category',
                    models.ForeignKey(
                        blank=True,
                        help_text='Категория расходов; пусто для общего лимита',
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='budgets',
                        to='transactions.category',
                        verbose_name='Категория',
                    ),
                ),
                (
                    'user',
                    models.ForeignKey(
                        db_index=True,
                        help_text='Пользователь, для которого задан бюджет',
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='budgets',
                        to=settings.AUTH_USER_MODEL,
                        verbose_name='Пользователь',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Бюджет',
                'verbose_name_plural': 'Бюджеты',
                'ordering': ['-period', 'category__name'],
            },
        ),
        migrations.AddConstraint(
            model_name='budget',
            constraint=models.UniqueConstraint(
                condition=Q(category__isnull=True),
                fields=('user', 'period'),
                name='unique_overall_budget_per_user_period',
            ),
        ),
        migrations.AddConstraint(
            model_name='budget',
            constraint=models.UniqueConstraint(
                condition=Q(category__isnull=False),
                fields=('user', 'category', 'period'),
                name='unique_category_budget_per_user_period',
            ),
        ),
        migrations.AddIndex(
            model_name='budget',
            index=models.Index(
                fields=['user', 'period'],
                name='budget_budg_user_id_6ecba7_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='budget',
            index=models.Index(
                fields=['user', 'category', 'period'],
                name='budget_budg_user_id_ad7d92_idx',
            ),
        ),
    ]
