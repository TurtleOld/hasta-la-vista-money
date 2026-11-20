"""Documented statement period bounds, never operation extrema."""

from datetime import date

from django.test import SimpleTestCase

from hasta_la_vista_money.users.tests.test_rosdorbank_source_errors import (
    _lines,
    _SyntheticRosDorParser,
)


class RosDorBankPeriodMetadataTest(SimpleTestCase):
    def test_header_sets_both_documented_bounds(self) -> None:
        result = _SyntheticRosDorParser(_lines()).parse()

        self.assertEqual(result.period_start, date(2026, 3, 1))
        self.assertEqual(result.period_end, date(2026, 3, 3))
