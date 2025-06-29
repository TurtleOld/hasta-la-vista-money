"""Асинхронные задачи для обработки чеков."""

import json
from typing import Any, Dict, Optional

import structlog
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Avg, Count, Max, Min, Sum
from django.utils import timezone
from hasta_la_vista_money.receipts.models import Product, Receipt, Seller
from hasta_la_vista_money.receipts.services import analyze_image_with_ai
from hasta_la_vista_money.users.models import User
from taskiq import Context, TaskiqDepends

logger = structlog.get_logger(__name__)


async def process_receipt_image(
    image_data: bytes,
    user_id: int,
    account_id: int,
    context: Context,
) -> Dict[str, Any]:
    """
    Асинхронная обработка изображения чека с AI.

    Args:
        image_data: Байты изображения
        user_id: ID пользователя
        account_id: ID счета
        context: Контекст задачи

    Returns:
        Результат обработки
    """
    logger.info(
        'Starting receipt image processing',
        user_id=user_id,
        account_id=account_id,
        image_size=len(image_data),
    )

    try:
        # Получаем объекты
        user = await User.objects.aget(id=user_id)
        account = await user.finance_account_users.aget(id=account_id)

        # Создаем временный файл для AI анализа
        from django.core.files.base import ContentFile

        temp_file = ContentFile(image_data, name='temp_receipt.jpg')

        # Анализируем изображение с AI
        json_receipt = await analyze_image_with_ai_async(temp_file)

        if not json_receipt:
            logger.error(
                'Failed to process image with AI',
                user_id=user_id,
                account_id=account_id,
            )
            return {'success': False, 'error': 'Не удалось обработать изображение'}

        # Парсим JSON
        receipt_data = json.loads(json_receipt)
        number_receipt = receipt_data.get('number_receipt')

        logger.info(
            'AI analysis completed',
            user_id=user_id,
            receipt_number=number_receipt,
            total_sum=receipt_data.get('total_sum'),
            items_count=len(receipt_data.get('items', [])),
        )

        # Проверяем существование чека
        existing_receipt = await Receipt.objects.filter(
            user=user,
            number_receipt=number_receipt,
        ).afirst()

        if existing_receipt:
            logger.warning(
                'Receipt already exists',
                user_id=user_id,
                receipt_number=number_receipt,
                existing_receipt_id=existing_receipt.pk,
            )
            return {'success': False, 'error': 'Чек с таким номером уже существует'}

        # Создаем продавца
        seller, created = await Seller.objects.aupdate_or_create(
            user=user,
            name_seller=receipt_data.get('name_seller', 'Неизвестный продавец'),
            defaults={
                'retail_place_address': receipt_data.get(
                    'retail_place_address',
                    'Нет данных',
                ),
                'retail_place': receipt_data.get('retail_place', 'Нет данных'),
            },
        )

        if created:
            logger.info(
                'Created new seller',
                user_id=user_id,
                seller_name=seller.name_seller,
                seller_id=seller.pk,
            )

        # Создаем товары
        products_data = []
        for item in receipt_data.get('items', []):
            products_data.append(
                Product(
                    user=user,
                    product_name=item['product_name'],
                    category=item.get('category', 'Общие товары'),
                    price=item['price'],
                    quantity=item['quantity'],
                    amount=item['amount'],
                ),
            )

        # Bulk create товаров
        products = await Product.objects.abulk_create(products_data)

        logger.info(
            'Created products',
            user_id=user_id,
            products_count=len(products),
        )

        # Создаем чек
        receipt = await Receipt.objects.acreate(
            user=user,
            account=account,
            number_receipt=number_receipt,
            receipt_date=receipt_data.get('receipt_date'),
            nds10=receipt_data.get('nds10', 0),
            nds20=receipt_data.get('nds20', 0),
            operation_type=receipt_data.get('operation_type', 1),
            total_sum=receipt_data.get('total_sum', 0),
            seller=seller,
        )

        # Добавляем товары к чеку
        await receipt.product.aadd(*products)

        logger.info(
            'Receipt processed successfully',
            user_id=user_id,
            receipt_id=receipt.pk,
            receipt_number=number_receipt,
            total_sum=str(receipt.total_sum),
            products_count=len(products),
            seller_name=seller.name_seller,
        )

        return {
            'success': True,
            'receipt_id': receipt.pk,
            'total_sum': str(receipt.total_sum),
            'products_count': len(products),
        }

    except Exception as e:
        logger.error(
            'Error processing receipt',
            user_id=user_id,
            account_id=account_id,
            error=str(e),
            exc_info=True,
        )
        return {'success': False, 'error': str(e)}


async def analyze_image_with_ai_async(image_file: UploadedFile) -> Optional[str]:
    """
    Асинхронная версия анализа изображения с AI.

    Args:
        image_file: Файл изображения

    Returns:
        JSON строка с данными чека
    """
    logger.info(
        'Starting AI image analysis',
        file_name=image_file.name,
        file_size=image_file.size,
    )

    try:
        # Временная заглушка - используем синхронную версию
        # В реальном проекте здесь будет асинхронный HTTP клиент
        result = analyze_image_with_ai(image_file)

        logger.info(
            'AI analysis completed successfully',
            file_name=image_file.name,
            result_length=len(result) if result else 0,
        )

        return result
    except Exception as e:
        logger.error(
            'AI analysis failed',
            file_name=image_file.name,
            error=str(e),
            exc_info=True,
        )
        return None


async def cleanup_old_receipts(
    days_old: int = 365,
    context: Context = TaskiqDepends(),
) -> Dict[str, Any]:
    """
    Очистка старых чеков.

    Args:
        days_old: Возраст чеков для удаления в днях
        context: Контекст задачи

    Returns:
        Результат очистки
    """
    logger.info(
        'Starting cleanup of old receipts',
        days_old=days_old,
    )

    try:
        cutoff_date = timezone.now() - timezone.timedelta(days=days_old)

        # Получаем старые чеки
        old_receipts_count = await Receipt.objects.filter(
            receipt_date__lt=cutoff_date,
        ).acount()

        logger.info(
            'Found old receipts for cleanup',
            old_receipts_count=old_receipts_count,
            cutoff_date=cutoff_date.isoformat(),
        )

        # Удаляем старые чеки
        deleted_count, _ = await Receipt.objects.filter(
            receipt_date__lt=cutoff_date,
        ).adelete()

        logger.info(
            'Cleanup completed',
            deleted_count=deleted_count,
            cutoff_date=cutoff_date.isoformat(),
        )

        return {
            'success': True,
            'deleted_count': deleted_count,
            'cutoff_date': cutoff_date.isoformat(),
        }

    except Exception as e:
        logger.error(
            'Error during cleanup',
            days_old=days_old,
            error=str(e),
            exc_info=True,
        )
        return {'success': False, 'error': str(e)}


async def generate_receipt_statistics(
    user_id: int,
    context: Context = TaskiqDepends(),
) -> Dict[str, Any]:
    """
    Генерация статистики по чекам пользователя.

    Args:
        user_id: ID пользователя
        context: Контекст задачи

    Returns:
        Статистика по чекам
    """
    logger.info(
        'Starting receipt statistics generation',
        user_id=user_id,
    )

    try:
        user = await User.objects.aget(id=user_id)

        # Агрегируем данные
        stats = await Receipt.objects.filter(user=user).aaggregate(
            total_receipts=Count('id'),
            total_sum=Sum('total_sum'),
            avg_sum=Avg('total_sum'),
            min_date=Min('receipt_date'),
            max_date=Max('receipt_date'),
        )

        # Статистика по продавцам
        seller_stats = (
            await Receipt.objects.filter(user=user)
            .values('seller__name_seller')
            .annotate(count=Count('id'), total=Sum('total_sum'))
            .order_by('-total')[:10]
        )

        logger.info(
            'Receipt statistics generated successfully',
            user_id=user_id,
            total_receipts=stats['total_receipts'],
            total_sum=str(stats['total_sum']),
            top_sellers_count=len(seller_stats),
        )

        return {
            'success': True,
            'user_id': user_id,
            'statistics': stats,
            'top_sellers': list(seller_stats),
        }

    except Exception as e:
        logger.error(
            'Error generating receipt statistics',
            user_id=user_id,
            error=str(e),
            exc_info=True,
        )
        return {'success': False, 'error': str(e)}
