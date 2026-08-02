from django.db import migrations

from hasta_la_vista_money.finance_account.bank_constants import SYSTEM_BANKS


def seed_system_banks(apps, schema_editor):
    Bank = apps.get_model('finance_account', 'Bank')
    for bank_def in SYSTEM_BANKS:
        Bank.objects.get_or_create(
            code=bank_def['code'],
            defaults={
                'name': bank_def['name'],
                'is_system': True,
            },
        )


def remove_system_banks(apps, schema_editor):
    Bank = apps.get_model('finance_account', 'Bank')
    codes = [b['code'] for b in SYSTEM_BANKS]
    Bank.objects.filter(code__in=codes).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('finance_account', '0019_create_bank_model'),
    ]

    operations = [
        migrations.RunPython(
            seed_system_banks,
            reverse_code=remove_system_banks,
        ),
    ]
