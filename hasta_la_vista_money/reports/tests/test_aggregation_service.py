from django.test import SimpleTestCase

from hasta_la_vista_money.reports.services.aggregation import (
    transform_dataset,
    unique_aggregate,
)


class AggregationPureFunctionsTests(SimpleTestCase):
    def test_transform_dataset(self) -> None:
        dataset = [
            {
                'date': __import__('datetime').date(2025, 1, 1),
                'total_amount': 10,
            },
            {
                'date': __import__('datetime').date(2025, 1, 2),
                'total_amount': 5.5,
            },
        ]
        dates, amounts = transform_dataset(dataset)
        self.assertEqual(dates, ['2025-01-01', '2025-01-02'])
        self.assertEqual(amounts, [10.0, 5.5])

    def test_unique_aggregate(self) -> None:
        dates = ['2025-01-01', '2025-01-01', '2025-01-02']
        amounts = [10.0, 5.0, 3.0]
        u_dates, u_amounts = unique_aggregate(dates, amounts)
        self.assertEqual(u_dates, ['2025-01-01', '2025-01-02'])
        self.assertEqual(u_amounts, [15.0, 3.0])
