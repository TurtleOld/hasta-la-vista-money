from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.db import migrations


def _create_search_indexes(_apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    seller_table = schema_editor.quote_name('receipts_seller')
    product_table = schema_editor.quote_name('receipts_product')
    seller_index = schema_editor.quote_name('receipts_seller_search_gin')
    product_index = schema_editor.quote_name('receipts_product_search_gin')

    schema_editor.execute(
        f'CREATE INDEX IF NOT EXISTS {seller_index} '
        f'ON {seller_table} USING GIN '
        "(to_tsvector('russian'::regconfig, coalesce(name_seller, '')))"
    )
    schema_editor.execute(
        f'CREATE INDEX IF NOT EXISTS {product_index} '
        f'ON {product_table} USING GIN '
        "(to_tsvector('russian'::regconfig, "
        "coalesce(product_name, '') || ' ' || coalesce(category, '')))"
    )


def _drop_search_indexes(_apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    seller_index = schema_editor.quote_name('receipts_seller_search_gin')
    product_index = schema_editor.quote_name('receipts_product_search_gin')

    schema_editor.execute(f'DROP INDEX IF EXISTS {seller_index}')
    schema_editor.execute(f'DROP INDEX IF EXISTS {product_index}')


class Migration(migrations.Migration):
    dependencies = [
        ('receipts', '0011_add_inn_to_seller'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name='seller',
                    index=GinIndex(
                        SearchVector('name_seller', config='russian'),
                        name='receipts_seller_search_gin',
                    ),
                ),
                migrations.AddIndex(
                    model_name='product',
                    index=GinIndex(
                        SearchVector(
                            'product_name',
                            'category',
                            config='russian',
                        ),
                        name='receipts_product_search_gin',
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(
                    _create_search_indexes,
                    _drop_search_indexes,
                ),
            ],
        ),
    ]
