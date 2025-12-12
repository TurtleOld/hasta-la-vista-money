"""Common mixins for views across the application."""

from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.db.models import QuerySet, Sum
from django.forms import BaseForm
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from django_stubs_ext import StrOrPromise
from rest_framework.request import Request as DRFRequest

from hasta_la_vista_money.services.views import get_cached_category_tree
from hasta_la_vista_money.users.models import User

if TYPE_CHECKING:
    from django_filters import FilterSet

    from hasta_la_vista_money.core.types import RequestWithContainer


class EntityListViewMixin:
    """Mixin для общих операций в списках сущностей (Expense, Income, Receipt).

    Предоставляет общие методы для:
    - Получения текущего пользователя
    - Работы с фильтрами
    - Вычисления totals
    - Работы с категориями
    """

    request: HttpRequest

    def get_current_user(self) -> User:
        """Получить текущего пользователя из request.

        Returns:
            User: Текущий аутентифицированный пользователь

        Raises:
            Http404: Если пользователь не найден
        """
        return get_object_or_404(User, username=self.request.user)

    def get_request_with_container(self) -> 'RequestWithContainer':
        """Получить request с контейнером dependency injection.

        Returns:
            RequestWithContainer: Request с контейнером
        """
        return cast('RequestWithContainer', self.request)

    def get_filtered_queryset(
        self,
        filterset_class: type['FilterSet'],
        base_queryset: QuerySet[Any],
    ) -> 'FilterSet':
        """Создать и применить фильтр к queryset.

        Args:
            filterset_class: Класс фильтра
            base_queryset: Базовый queryset для фильтрации

        Returns:
            FilterSet: Применённый фильтр
        """
        request = self.get_request_with_container()
        return filterset_class(  # type: ignore[call-arg]
            self.request.GET,
            queryset=base_queryset,
            user=request.user,
        )

    def calculate_total_amount(
        self,
        queryset: QuerySet[Any],
        amount_field: str = 'amount',
    ) -> dict[str, Any]:
        """Вычислить общую сумму из queryset.

        Args:
            queryset: QuerySet для вычисления суммы
            amount_field: Название поля с суммой

        Returns:
            dict: Словарь с ключом 'total' и значением суммы
        """
        return queryset.aggregate(total=Sum(amount_field))

    def get_total_amount_value(
        self,
        queryset: QuerySet[Any],
        amount_field: str = 'amount',
    ) -> float:
        """Получить значение общей суммы из queryset.

        Args:
            queryset: QuerySet для вычисления суммы
            amount_field: Название поля с суммой

        Returns:
            float: Общая сумма или 0 если None
        """
        result = self.calculate_total_amount(queryset, amount_field)
        return float(result.get('total') or 0)

    def get_flattened_categories(
        self,
        categories: list[dict[str, Any]] | QuerySet[Any],
        category_type: str,
        depth: int = 3,
    ) -> list[dict[str, Any]]:
        """Получить плоское дерево категорий с кешированием.

        Args:
            categories: Список или QuerySet категорий
            category_type: Тип категорий ('expense' или 'income')
            depth: Глубина дерева категорий

        Returns:
            list: Список категорий в виде дерева
        """
        user = self.get_current_user()
        categories_list = (
            [dict(cat) for cat in categories]
            if hasattr(categories, 'values')
            else categories
        )
        return get_cached_category_tree(
            user_id=user.pk,
            category_type=category_type,
            categories=categories_list,
            depth=depth,
        )


class UserAuthMixin:
    """Mixin для автоматической проверки типа пользователя.

    Автоматически проверяет, что request.user является экземпляром User,
    и выбрасывает TypeError если это не так. Это устраняет необходимость
    повторять проверку isinstance(request.user, User) в каждом методе view.
    """

    def dispatch(
        self,
        request: HttpRequest | DRFRequest,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Переопределяет dispatch для проверки типа пользователя.

        Args:
            request: HTTP запрос
            *args: Дополнительные позиционные аргументы
            **kwargs: Дополнительные именованные аргументы

        Returns:
            HttpResponse или Response: Ответ view

        Raises:
            TypeError: Если request.user не является экземпляром User
        """
        if not isinstance(request.user, User):
            raise TypeError('User must be authenticated')
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

    def get_authenticated_user(self) -> User:
        """Получить аутентифицированного пользователя с проверкой типа.

        Returns:
            User: Аутентифицированный пользователь

        Raises:
            TypeError: Если request.user не является экземпляром User
        """
        request = self.request
        if not isinstance(request.user, User):
            raise TypeError('User must be authenticated')
        return request.user


class FormErrorHandlingMixin:
    """Mixin для обработки ошибок форм.

    Предоставляет общие методы для обработки ошибок при работе с формами,
    устраняя дублирование кода обработки исключений.
    """

    def handle_form_error_with_message(
        self,
        form: BaseForm,
        error: Exception,
        error_message_template: StrOrPromise,
        **kwargs: Any,
    ) -> HttpResponse:
        """Обработать ошибку формы с сообщением через messages framework.

        Args:
            form: Форма с ошибкой
            error: Исключение, которое произошло
            error_message_template: Шаблон сообщения об ошибке
            **kwargs: Дополнительные именованные аргументы для форматирования

        Returns:
            HttpResponse: Ответ с невалидной формой
        """
        error_message = error_message_template.format(
            error=str(error),
            **kwargs,
        )
        request = self.request
        if isinstance(request, HttpRequest):
            messages.error(request, _(error_message))
        return cast(
            'HttpResponse',
            self.form_invalid(form),  # type: ignore[attr-defined]
        )

    def handle_form_error_with_field_error(
        self,
        form: BaseForm,
        error: Exception,
        field: str | None = None,
    ) -> HttpResponse:
        """Обработать ошибку формы, добавив её в поле формы.

        Args:
            form: Форма с ошибкой
            error: Исключение, которое произошло
            field: Имя поля для ошибки (None для общей ошибки формы)

        Returns:
            HttpResponse: Ответ с невалидной формой
        """
        form.add_error(field, str(error))
        return cast(
            'HttpResponse',
            self.form_invalid(form),  # type: ignore[attr-defined]
        )

    def handle_ajax_error(
        self,
        error: Exception,
        status_code: int = 500,
    ) -> JsonResponse:
        """Обработать ошибку для AJAX запроса.

        Args:
            error: Исключение, которое произошло
            status_code: HTTP статус код для ответа

        Returns:
            JsonResponse: JSON ответ с ошибкой
        """
        return JsonResponse({'error': str(error)}, status=status_code)

    def handle_ajax_error_with_success_flag(
        self,
        error: Exception,
    ) -> JsonResponse:
        """Обработать ошибку для AJAX запроса с флагом success.

        Args:
            error: Исключение, которое произошло

        Returns:
            JsonResponse: JSON ответ с флагом success=False и ошибкой
        """
        return JsonResponse({'success': False, 'error': str(error)})

    def handle_service_error(
        self,
        form: BaseForm,
        error: Exception,
        error_message_template: str | None = None,
        use_field_error: bool = False,
    ) -> HttpResponse:
        """Обработать ошибку сервиса при работе с формой.

        Универсальный метод для обработки ValueError, TypeError,
        PermissionDenied.

        Args:
            form: Форма с ошибкой
            error: Исключение (ValueError, TypeError, PermissionDenied)
            error_message_template: Шаблон сообщения об ошибке
            use_field_error: Если True, использовать form.add_error

        Returns:
            HttpResponse: Ответ с невалидной формой
        """
        if use_field_error:
            return self.handle_form_error_with_field_error(form, error)
        if error_message_template:
            return self.handle_form_error_with_message(
                form,
                error,
                error_message_template,
            )
        return self.handle_form_error_with_field_error(form, error)
