from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0013_bankstatementcandidate'),
    ]

    operations = [
        migrations.AddField(
            model_name='bankstatementupload',
            name='awaiting_decision_count',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='bankstatementupload',
            name='expired_count',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='bankstatementupload',
            name='failed_count',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='bankstatementupload',
            name='imported_count',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='bankstatementupload',
            name='linked_count',
            field=models.IntegerField(default=0),
        ),
    ]
