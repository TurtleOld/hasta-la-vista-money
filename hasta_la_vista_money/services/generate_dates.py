from datetime import date, datetime
from typing import Optional, Union

from dateutil.relativedelta import relativedelta
from django.db.models import QuerySet
from hasta_la_vista_money import constants
from hasta_la_vista_money.budget.models import DateList, Planning
from hasta_la_vista_money.expense.models import ExpenseCategory
from hasta_la_vista_money.income.models import IncomeCategory
from hasta_la_vista_money.users.models import User


def generate_date_list(
    current_date: Union[datetime, QuerySet[DateList, DateList]],
    user: User,
    type_: Optional[str] = None,
) -> None:
    """
    Добавляет 12 новых месяцев после самой последней даты пользователя.
    Если type_ задан, добавляет только для расходов или только для доходов (в Planning).
    """
    actual_date: Union[datetime, date]
    if isinstance(current_date, QuerySet):
        last_date_instance = current_date.last()
        if last_date_instance is not None:
            actual_date = last_date_instance.date
        else:
            raise ValueError('current_date must be datetime or QuerySet')
    else:
        actual_date = current_date

    last_date_obj = DateList.objects.filter(user=user).order_by('-date').first()
    if last_date_obj:
        start_date = last_date_obj.date + relativedelta(months=1)
    else:
        start_date = actual_date

    new_dates = [
        start_date + relativedelta(months=i)
        for i in range(constants.NUMBER_TWELFTH_MONTH_YEAR)
    ]

    existing_dates = set(
        DateList.objects.filter(user=user, date__in=new_dates).values_list(
            'date',
            flat=True,
        ),
    )

    dates_to_create = []
    for d in new_dates:
        if d not in existing_dates:
            dates_to_create.append(DateList(user=user, date=d))

    if dates_to_create:
        DateList.objects.bulk_create(dates_to_create)

    planning_to_create = []

    for d in new_dates:
        if type_ == 'expense':
            expense_categories: QuerySet[ExpenseCategory] = (
                ExpenseCategory.objects.filter(user=user)
            )
            for cat in expense_categories:
                if not Planning.objects.filter(
                    user=user,
                    category_expense=cat,
                    date=d,
                    type='expense',
                ).exists():
                    planning_to_create.append(
                        Planning(
                            user=user,
                            category_expense=cat,
                            date=d,
                            type='expense',
                            amount=0,
                        ),
                    )
        elif type_ == 'income':
            income_categories: QuerySet[IncomeCategory] = IncomeCategory.objects.filter(
                user=user,
            )
            for cat in income_categories:
                if not Planning.objects.filter(
                    user=user,
                    category_income=cat,
                    date=d,
                    type='income',
                ).exists():
                    planning_to_create.append(
                        Planning(
                            user=user,
                            category_income=cat,
                            date=d,
                            type='income',
                            amount=0,
                        ),
                    )

    if planning_to_create:
        Planning.objects.bulk_create(planning_to_create)
