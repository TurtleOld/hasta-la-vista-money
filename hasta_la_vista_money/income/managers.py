from django.db import models
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth


class IncomeQuerySet(models.QuerySet):
    """
    Custom QuerySet for Income model with advanced filtering and aggregation.
    """

    def for_user(self, user):
        """Return incomes for a specific user."""
        return self.filter(user=user)

    def for_period(self, start_date, end_date):
        """Return incomes within a date range."""
        return self.filter(date__gte=start_date, date__lte=end_date)

    def for_category(self, category):
        """Return incomes for a specific category or its descendants."""
        return self.filter(
            Q(category=category) | Q(category__parent_category=category),
        )

    def total_amount(self):
        """Return the total amount for the queryset."""
        return self.aggregate(total=Sum('amount'))['total'] or 0

    def by_month(self):
        """Return incomes grouped by month."""
        return (
            self.annotate(month=TruncMonth('date'))
            .values('month')
            .annotate(total=Sum('amount'))
            .order_by('month')
        )


class IncomeManager(models.Manager):
    """
    Custom manager for Income model.
    """

    def get_queryset(self):
        return IncomeQuerySet(self.model, using=self._db)

    def for_user(self, user):
        return self.get_queryset().for_user(user)

    def for_period(self, start_date, end_date):
        return self.get_queryset().for_period(start_date, end_date)

    def for_category(self, category):
        return self.get_queryset().for_category(category)

    def total_amount(self):
        return self.get_queryset().total_amount()

    def by_month(self):
        return self.get_queryset().by_month()
