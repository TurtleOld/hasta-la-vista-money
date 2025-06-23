from datetime import datetime
from dateutil.relativedelta import relativedelta
from django.db.models import QuerySet
from hasta_la_vista_money import constants
from hasta_la_vista_money.budget.models import DateList
from hasta_la_vista_money.users.models import User


def generate_date_list(
    current_date: datetime | QuerySet[DateList],
    user: User,
):
    """
    Добавляет 12 новых месяцев после самой последней даты пользователя.
    """
    if isinstance(current_date, QuerySet):
        last_date_instance = current_date.last()
        if last_date_instance is not None:
            current_date = last_date_instance.date
        else:
            raise ValueError('current_date must be datetime or QuerySet')

    last_date_obj = DateList.objects.filter(user=user).order_by('-date').first()
    if last_date_obj:
        start_date = last_date_obj.date + relativedelta(months=1)
    else:
        start_date = current_date

    new_dates = [
        start_date + relativedelta(months=i)
        for i in range(constants.NUMBER_TWELFTH_MONTH_YEAR)
    ]

    existing_dates = set(
        DateList.objects.filter(user=user, date__in=new_dates).values_list(
            'date', flat=True
        )
    )
    for d in new_dates:
        if d not in existing_dates:
            DateList.objects.create(user=user, date=d)
