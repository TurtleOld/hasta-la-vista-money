from django.db import migrations, models
import django.db.models.deletion


def migrate_account_bank_to_fk(apps, schema_editor):
    Account = apps.get_model('finance_account', 'Account')
    Bank = apps.get_model('finance_account', 'Bank')

    default_bank = Bank.objects.filter(code='-').first()
    if default_bank is None:
        return

    for account in Account.objects.all():
        code = account.bank_old
        bank = Bank.objects.filter(code=code).first()
        if bank is None:
            bank = default_bank
        account.bank_new = bank
        account.save(update_fields=['bank_new'])


class Migration(migrations.Migration):
    dependencies = [
        ('finance_account', '0020_seed_system_banks'),
    ]

    operations = [
        migrations.RenameField(
            model_name='account',
            old_name='bank',
            new_name='bank_old',
        ),
        migrations.AddField(
            model_name='account',
            name='bank_new',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to='finance_account.Bank',
                verbose_name='Банк',
                help_text='Банк, выпустивший карту или обслуживающий счёт',
            ),
        ),
        migrations.RunPython(
            migrate_account_bank_to_fk,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name='account',
            name='bank_old',
        ),
        migrations.RenameField(
            model_name='account',
            old_name='bank_new',
            new_name='bank',
        ),
    ]
