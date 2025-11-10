from collections.abc import Sequence
from datetime import date, datetime

from dateutil.relativedelta import relativedelta
from django.db.models import QuerySet

from hasta_la_vista_money import constants
from hasta_la_vista_money.budget.models import DateList, Planning
from hasta_la_vista_money.expense.models import ExpenseCategory
from hasta_la_vista_money.income.models import IncomeCategory
from hasta_la_vista_money.users.models import User


class DateListGenerator:
    """Создаёт недостающие месяцы и плановые записи для пользователя."""

    def __init__(self, user: User, type_: str | None) -> None:
        """Сохранить параметры генерации."""
        self.user = user
        self.type_ = type_

    def run(self, current_date: datetime | QuerySet[DateList]) -> None:
        """Добавить 12 следующих месяцев и, при необходимости, Planning."""
        actual = self._actual_date(current_date)
        start = self._start_date(actual)
        months = self._month_sequence(
            start,
            constants.NUMBER_TWELFTH_MONTH_YEAR,
        )
        self._ensure_dates(months)
        self._ensure_planning(months)

    def _actual_date(
        self, current_date: datetime | QuerySet[DateList] | date
    ) -> date:
        """Вернуть опорную дату из datetime или QuerySet."""
        if isinstance(current_date, QuerySet):
            last = current_date.last()
            if last is None:
                error_msg = 'current_date must be datetime or QuerySet'
                raise ValueError(error_msg)
            return last.date
        if isinstance(current_date, datetime):
            return current_date.date()
        return current_date

    def _start_date(self, actual: date) -> date:
        """Вернуть месяц после последней даты в DateList или actual."""
        last_obj = (
            DateList.objects.filter(user=self.user).order_by('-date').first()
        )
        return last_obj.date + relativedelta(months=1) if last_obj else actual

    def _month_sequence(self, start: date, count: int) -> list[date]:
        """Сгенерировать последовательность месяцев от start включительно."""
        return [start + relativedelta(months=i) for i in range(count)]

    def _ensure_dates(self, months: Sequence[date]) -> None:
        """Создать записи DateList для отсутствующих дат."""
        existing = set(
            DateList.objects.filter(
                user=self.user,
                date__in=months,
            ).values_list('date', flat=True),
        )
        to_create = [
            DateList(user=self.user, date=d)
            for d in months
            if d not in existing
        ]
        if to_create:
            DateList.objects.bulk_create(to_create)

    def _ensure_planning(self, months: Sequence[date]) -> None:
        """Создать недостающие Planning по заданному типу."""
        if self.type_ not in {'expense', 'income'}:
            return

        if self.type_ == 'expense':
            expense_cats = list(ExpenseCategory.objects.filter(user=self.user))
            existing = set(
                Planning.objects.filter(
                    user=self.user,
                    planning_type='expense',
                    date__in=months,
                    category_expense__in=expense_cats,
                ).values_list('category_expense_id', 'date'),
            )
            to_create = [
                Planning(
                    user=self.user,
                    category_expense=c,
                    date=d,
                    planning_type='expense',
                    amount=0,
                )
                for c in expense_cats
                for d in months
                if (c.pk, d) not in existing
            ]
        else:
            income_cats: list[IncomeCategory] = list(
                IncomeCategory.objects.filter(user=self.user),
            )
            existing = set(
                Planning.objects.filter(
                    user=self.user,
                    planning_type='income',
                    date__in=months,
                    category_income__in=income_cats,
                ).values_list('category_income_id', 'date'),
            )
            to_create = [
                Planning(
                    user=self.user,
                    category_income=c,
                    date=d,
                    planning_type='income',
                    amount=0,
                )
                for c in income_cats
                for d in months
                if (c.pk, d) not in existing
            ]

        if to_create:
            Planning.objects.bulk_create(to_create)


def generate_date_list(
    current_date: datetime | QuerySet[DateList],
    user: User,
    type_: str | None = None,
) -> None:
    """Добавить месяцы и при необходимости Planning без дублей."""
    DateListGenerator(user=user, type_=type_).run(current_date)
