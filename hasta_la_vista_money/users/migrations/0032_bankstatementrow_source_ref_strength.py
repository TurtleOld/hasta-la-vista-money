from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('users', '0031_merge_statement_rollout'),
    ]

    operations = [
        migrations.AddField(
            model_name='bankstatementrow',
            name='source_ref_strength',
            field=models.CharField(blank=True, default='weak', max_length=10),
        ),
    ]
