from django.test import SimpleTestCase

from hasta_la_vista_money.expense.templatetags.expense_tags import startswith


class ExpenseTemplateTagsTest(SimpleTestCase):
    def test_startswith_returns_true(self) -> None:
        self.assertTrue(startswith('category:food', 'category'))

    def test_startswith_returns_false(self) -> None:
        self.assertFalse(startswith('category:food', 'expense'))

