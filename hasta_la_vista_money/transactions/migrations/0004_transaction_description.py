from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0003_transaction_source_file_hash_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='description',
            field=models.CharField(blank=True, default='', max_length=250),
        ),
    ]
