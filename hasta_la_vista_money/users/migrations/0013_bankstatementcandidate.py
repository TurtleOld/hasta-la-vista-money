import django.db.models.deletion
from django.db import migrations, models


def copy_existing_candidates(apps, schema_editor):
    statement_row = apps.get_model('users', 'BankStatementRow')
    statement_candidate = apps.get_model(
        'users',
        'BankStatementCandidate',
    )
    statement_candidate.objects.bulk_create(
        [
            statement_candidate(
                row_id=row.pk,
                transaction_id=row.candidate_id,
                description=row.candidate_description,
                rank=0,
            )
            for row in statement_row.objects.exclude(
                candidate_id=None,
            ).iterator()
        ],
    )


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0004_transaction_description'),
        ('users', '0012_bankstatementrow'),
    ]

    operations = [
        migrations.AddField(
            model_name='bankstatementrow',
            name='match_calendar_date',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='bankstatementrow',
            name='candidate',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='statement_candidates',
                to='transactions.transaction',
            ),
        ),
        migrations.CreateModel(
            name='BankStatementCandidate',
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
                ('description', models.CharField(max_length=250)),
                ('rank', models.PositiveIntegerField(default=0)),
                (
                    'row',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='candidates',
                        to='users.bankstatementrow',
                    ),
                ),
                (
                    'transaction',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='statement_candidate_links',
                        to='transactions.transaction',
                    ),
                ),
            ],
            options={
                'ordering': ['rank', 'pk'],
                'constraints': [
                    models.UniqueConstraint(
                        fields=('row', 'transaction'),
                        name='unique_statement_row_candidate',
                    ),
                ],
            },
        ),
        migrations.RunPython(
            copy_existing_candidates,
            migrations.RunPython.noop,
        ),
    ]
