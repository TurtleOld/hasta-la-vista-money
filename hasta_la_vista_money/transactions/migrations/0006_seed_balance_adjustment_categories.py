from django.db import migrations
from django.db.models.functions import Lower

# Frozen on purpose: migrations must not follow later constant changes.
KIND = 'balance_adjustment'
NAME = 'Корректировка остатка'
LEGACY_NAMES = {NAME.lower(), 'корректировка баланса'}


def seed_balance_adjustment_categories(apps, _schema_editor):
    """Promote legacy adjustment categories, create the missing ones."""
    Category = apps.get_model('transactions', 'Category')
    User = apps.get_model('users', 'User')
    for user_id in User.objects.values_list('pk', flat=True):
        for type_value in ('income', 'expense'):
            categories = Category.objects.filter(
                user_id=user_id,
                type=type_value,
            )
            oldest = (
                categories.annotate(lowered=Lower('name'))
                .filter(lowered__in=LEGACY_NAMES)
                .order_by('pk')
                .first()
            )
            if oldest is None:
                Category.objects.create(
                    user_id=user_id,
                    type=type_value,
                    name=NAME,
                    system_kind=KIND,
                )
                continue
            # Free the target name for the promoted category.
            categories.filter(name=NAME).exclude(pk=oldest.pk).update(
                name=f'{NAME} (прежняя)',
            )
            oldest.name = NAME
            oldest.system_kind = KIND
            oldest.save(update_fields=['name', 'system_kind'])


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0005_category_system_kind'),
    ]

    operations = [
        migrations.RunPython(
            seed_balance_adjustment_categories,
            migrations.RunPython.noop,
        ),
    ]
