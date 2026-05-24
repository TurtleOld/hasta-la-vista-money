"""Squashed initial migration for the budget app.

Replaces 0001-0007 to drop historical dependencies on the removed
``income`` and ``expense`` apps. Already-applied installations will be
recognised via ``replaces``.
"""

import datetime
from typing import ClassVar

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    replaces: ClassVar[list[tuple[str, str]]] = [
        ('budget', '0001_initial'),
        ('budget', '0002_initial'),
        ('budget', '0003_planning_amount_planning_category_expense_and_more'),
        ('budget', '0004_alter_datelist_options_alter_planning_options_and_more'),
        ('budget', '0005_remove_planning_unique_planning_per_user_category_date_type_and_more'),
        ('budget', '0006_planning_planning_category_matches_type'),
        ('budget', '0007_planning_unified_category'),
    ]

    dependencies = [
        ('transactions', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DateList',
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
                    'date',
                    models.DateField(
                        db_index=True,
                        default=datetime.date.today,
                        help_text='Дата планирования',
                        verbose_name='Дата',
                    ),
                ),
                (
                    'created_at',
                    models.DateTimeField(
                        auto_now_add=True,
                        blank=True,
                        help_text='Когда запись была создана',
                        null=True,
                        verbose_name='Дата создания',
                    ),
                ),
                (
                    'user',
                    models.ForeignKey(
                        help_text=(
                            'Пользователь, для которого ведется список дат'
                        ),
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='budget_date_lists',
                        to=settings.AUTH_USER_MODEL,
                        verbose_name='Пользователь',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Список дат',
                'verbose_name_plural': 'Списки дат',
                'ordering': ['-date'],
            },
        ),
        migrations.AddIndex(
            model_name='datelist',
            index=models.Index(
                fields=['user', 'date'],
                name='budget_date_user_id_4ab954_idx',
            ),
        ),
        migrations.CreateModel(
            name='Planning',
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
                    'date',
                    models.DateField(
                        db_index=True,
                        default=datetime.date.today,
                        help_text='Дата планирования',
                        verbose_name='Дата',
                    ),
                ),
                (
                    'amount',
                    models.DecimalField(
                        decimal_places=2,
                        default=0,
                        help_text='Планируемая сумма',
                        max_digits=12,
                        verbose_name='Сумма',
                    ),
                ),
                (
                    'planning_type',
                    models.CharField(
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
                (
                    'created_at',
                    models.DateTimeField(
                        auto_now_add=True,
                        blank=True,
                        help_text='Когда запись была создана',
                        null=True,
                        verbose_name='Дата создания',
                    ),
                ),
                (
                    'category',
                    models.ForeignKey(
                        help_text='Категория операции',
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='plannings',
                        to='transactions.category',
                        verbose_name='Категория',
                    ),
                ),
                (
                    'user',
                    models.ForeignKey(
                        db_index=True,
                        help_text=(
                            'Пользователь, для которого ведется планирование'
                        ),
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='plannings',
                        to=settings.AUTH_USER_MODEL,
                        verbose_name='Пользователь',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Планирование',
                'verbose_name_plural': 'Планирования',
                'ordering': ['-date'],
            },
        ),
        migrations.AddConstraint(
            model_name='planning',
            constraint=models.UniqueConstraint(
                fields=('user', 'category', 'date', 'planning_type'),
                name='unique_planning_per_user_category_date_type',
            ),
        ),
        migrations.AddIndex(
            model_name='planning',
            index=models.Index(
                fields=['user', 'date', 'planning_type'],
                name='budget_plan_user_id_2ee358_idx',
            ),
        ),
    ]
