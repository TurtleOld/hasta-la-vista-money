from django.db import migrations


def fix_currency(apps, schema_editor):  # noqa: ARG001
    Account = apps.get_model('finance_account', 'Account')
    Account.objects.filter(currency='RU').update(currency='RUB')


class Migration(migrations.Migration):
    dependencies = [
        ('finance_account', '0024_add_external_id_and_audit'),
    ]

    operations = [
        migrations.RunPython(fix_currency, migrations.RunPython.noop),
    ]
