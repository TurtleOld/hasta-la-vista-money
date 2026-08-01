from datetime import timedelta

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import F

import hasta_la_vista_money.users.models


def set_existing_expiration_deadlines(apps, _schema_editor):
    """Set existing deadlines to 30 days after their upload date."""
    upload_model = apps.get_model('users', 'BankStatementUpload')
    upload_model.objects.update(
        expires_at=F('created_at') + timedelta(days=30),
    )


class Migration(migrations.Migration):
    dependencies = [
        ('transactions', '0004_transaction_description'),
        ('users', '0014_bankstatementupload_outcome_counts'),
    ]

    operations = [
        migrations.AddField(
            model_name='bankstatementupload',
            name='expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(
            set_existing_expiration_deadlines,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='bankstatementupload',
            name='expires_at',
            field=models.DateTimeField(
                default=hasta_la_vista_money.users.models.bank_statement_expires_at,
            ),
        ),
        migrations.AddField(
            model_name='bankstatementupload',
            name='retention_cleaned_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='bankstatementrow',
            name='amount',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=20,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='bankstatementrow',
            name='candidate_description',
            field=models.CharField(blank=True, default='', max_length=250),
        ),
        migrations.AlterField(
            model_name='bankstatementrow',
            name='decision',
            field=models.CharField(
                choices=[
                    ('pending', 'Ожидает решения'),
                    ('linked', 'Уже учтена'),
                    ('new', 'Новая операция'),
                    ('expired', 'Срок решения истёк'),
                ],
                default='pending',
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name='bankstatementrow',
            name='description',
            field=models.CharField(blank=True, default='', max_length=250),
        ),
        migrations.AlterField(
            model_name='bankstatementrow',
            name='source_row_position',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='bankstatementrow',
            name='suggested_category',
            field=models.CharField(blank=True, default='', max_length=250),
        ),
        migrations.AlterField(
            model_name='bankstatementrow',
            name='transaction',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='statement_rows',
                to='transactions.transaction',
            ),
        ),
        migrations.AlterField(
            model_name='bankstatementrow',
            name='transaction_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='bankstatementrow',
            name='transaction_type',
            field=models.CharField(
                blank=True,
                choices=[('income', 'Доход'), ('expense', 'Расход')],
                max_length=10,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='bankstatementupload',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'В очереди'),
                    ('processing', 'Обрабатывается'),
                    ('awaiting_confirmation', 'Ожидает подтверждения'),
                    ('completed', 'Завершено'),
                    (
                        'completed_with_unresolved',
                        'Завершено с нерешёнными строками',
                    ),
                    ('failed', 'Ошибка'),
                ],
                default='pending',
                max_length=25,
            ),
        ),
        migrations.CreateModel(
            name='BankStatementDecisionAudit',
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
                    'decision',
                    models.CharField(
                        choices=[
                            ('pending', 'Ожидает решения'),
                            ('linked', 'Уже учтена'),
                            ('new', 'Новая операция'),
                            ('expired', 'Срок решения истёк'),
                        ],
                        max_length=10,
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'actor',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='statement_decision_audits',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'previous_transaction',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='previous_statement_decision_audits',
                        to='transactions.transaction',
                    ),
                ),
                (
                    'row',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='decision_audits',
                        to='users.bankstatementrow',
                    ),
                ),
                (
                    'transaction',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='statement_decision_audits',
                        to='transactions.transaction',
                    ),
                ),
            ],
            options={
                'ordering': ['created_at', 'pk'],
            },
        ),
    ]
