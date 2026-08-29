import django.contrib.postgres.indexes
import django.contrib.postgres.search
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from hasta_la_vista_money import constants
from hasta_la_vista_money.receipts.product_category_constants import (
    normalize_product_category_name,
)
from hasta_la_vista_money.receipts.product_category_migration_data import (
    PRODUCT_CATEGORY_EXCEPTIONS,
    PRODUCT_CATEGORY_MAPPINGS,
)


def remove_product_search_index(apps, schema_editor):
    """Remove the legacy index only where the previous migration created it."""
    del apps
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(
            'DROP INDEX IF EXISTS receipts_product_search_gin'
        )


def add_product_search_index(apps, schema_editor):
    """Create the replacement index only on PostgreSQL."""
    del apps
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(
            'CREATE INDEX IF NOT EXISTS receipts_product_search_gin '
            'ON receipts_product USING GIN '
            "(to_tsvector('russian'::regconfig, "
            "coalesce(product_name, '')))"
        )


def migrate_product_categories(apps, schema_editor):
    """Move free-text categories to each user's product directory."""
    del schema_editor
    Product = apps.get_model('receipts', 'Product')
    ProductCategory = apps.get_model('receipts', 'ProductCategory')
    app_label, model_name = settings.AUTH_USER_MODEL.split('.')
    User = apps.get_model(app_label, model_name)

    for user in User.objects.all().iterator():
        ProductCategory.objects.bulk_create(
            [
                ProductCategory(
                    user_id=user.pk,
                    name=name,
                    normalized_name=normalize_product_category_name(name),
                )
                for name in constants.STARTER_PRODUCT_CATEGORIES
            ],
            ignore_conflicts=True,
        )
        category_ids = {
            category.name: category.pk
            for category in ProductCategory.objects.filter(user_id=user.pk)
        }
        for product in Product.objects.filter(user_id=user.pk).iterator():
            old_category = (product.category or '').strip()
            if product.product_name == 'Возврат оплаты':
                category_id = None
            else:
                target = PRODUCT_CATEGORY_EXCEPTIONS.get(
                    (old_category, product.product_name),
                    PRODUCT_CATEGORY_MAPPINGS.get(
                        old_category,
                        constants.DEFAULT_PRODUCT_CATEGORY,
                    ),
                )
                category_id = category_ids[target]
            product.product_category_id = category_id
            product.category_source = 'migrated'
            product.save(update_fields=['product_category', 'category_source'])


class Migration(migrations.Migration):
    dependencies = [
        ('receipts', '0014_pendingreceipt_converted_receipt_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductCategory',
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
                ('name', models.CharField(max_length=250)),
                ('normalized_name', models.CharField(max_length=250)),
                (
                    'user',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='product_categories',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={'ordering': ['name']},
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveIndex(
                    model_name='product',
                    name='receipts_product_search_gin',
                ),
            ],
            database_operations=[
                migrations.RunPython(
                    remove_product_search_index,
                    migrations.RunPython.noop,
                ),
            ],
        ),
        migrations.AddField(
            model_name='product',
            name='category_source',
            field=models.CharField(
                choices=[
                    ('migrated', 'Перенесено'),
                    ('name_match', 'Закреплённое сопоставление'),
                    ('writing_match', 'Подбор по написанию'),
                    ('semantic_match', 'Подбор по смыслу'),
                    ('external_model', 'Внешняя модель'),
                    ('manual', 'Поставлено человеком'),
                ],
                default='migrated',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='product_category',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='products',
                to='receipts.productcategory',
            ),
        ),
        migrations.RunPython(
            migrate_product_categories,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='product',
            name='category_source',
            field=models.CharField(
                choices=[
                    ('migrated', 'Перенесено'),
                    ('name_match', 'Закреплённое сопоставление'),
                    ('writing_match', 'Подбор по написанию'),
                    ('semantic_match', 'Подбор по смыслу'),
                    ('external_model', 'Внешняя модель'),
                    ('manual', 'Поставлено человеком'),
                ],
                default='writing_match',
                max_length=20,
            ),
        ),
        migrations.RemoveField(model_name='product', name='category'),
        migrations.RenameField(
            model_name='product',
            old_name='product_category',
            new_name='category',
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name='product',
                    index=django.contrib.postgres.indexes.GinIndex(
                        django.contrib.postgres.search.SearchVector(
                            'product_name',
                            config='russian',
                        ),
                        name='receipts_product_search_gin',
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(
                    add_product_search_index,
                    migrations.RunPython.noop,
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name='productcategory',
            constraint=models.UniqueConstraint(
                fields=('user', 'normalized_name'),
                name='unique_user_normalized_product_category',
            ),
        ),
    ]
