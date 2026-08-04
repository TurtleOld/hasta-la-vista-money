from django.db import migrations, models
import django.db.models.deletion


def migrate_deposit_bank_to_fk(apps, schema_editor):
    Deposit = apps.get_model('deposits', 'Deposit')
    Bank = apps.get_model('finance_account', 'Bank')

    default_bank = Bank.objects.filter(code='-').first()
    if default_bank is None:
        return

    for deposit in Deposit.objects.all():
        code = deposit.bank_old
        bank = Bank.objects.filter(code=code).first()
        if bank is None:
            bank = default_bank
        deposit.bank_new = bank
        deposit.save(update_fields=['bank_new'])


class Migration(migrations.Migration):
    dependencies = [
        ('deposits', '0007_add_capitalization_event'),
        ('finance_account', '0021_migrate_account_bank_to_fk'),
    ]

    operations = [
        migrations.RenameField(
            model_name='deposit',
            old_name='bank',
            new_name='bank_old',
        ),
        migrations.AddField(
            model_name='deposit',
            name='bank_new',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='deposits',
                to='finance_account.Bank',
                verbose_name='Банк',
            ),
        ),
        migrations.RunPython(
            migrate_deposit_bank_to_fk,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name='deposit',
            name='bank_old',
        ),
        migrations.RenameField(
            model_name='deposit',
            old_name='bank_new',
            new_name='bank',
        ),
    ]
