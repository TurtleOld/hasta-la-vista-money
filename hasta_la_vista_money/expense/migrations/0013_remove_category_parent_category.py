# Generated by Django 4.2.7 on 2023-11-12 17:19

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('expense', '0012_remove_expense_parent_category_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='category',
            name='parent_category',
        ),
    ]
