from django.test import SimpleTestCase

from hasta_la_vista_money.templatetags.index import diff_by_index, div, index


class IndexTemplateTagsTest(SimpleTestCase):
    def test_index_returns_value(self) -> None:
        sequence = ['a', 'b', 'c']
        self.assertEqual(index(sequence, 1), 'b')

    def test_index_handles_errors(self) -> None:
        self.assertEqual(index(['a'], 3), '')
        self.assertEqual(index(None, 0), '')

    def test_diff_by_index_returns_difference(self) -> None:
        list1 = [10, 20, 30]
        list2 = [1, 2, 3]
        self.assertEqual(diff_by_index(list1, list2, 2), 27)

    def test_diff_by_index_handles_errors(self) -> None:
        self.assertEqual(diff_by_index([1], [1], 5), '')
        self.assertEqual(diff_by_index(None, [1], 0), '')

    def test_div_returns_percentage(self) -> None:
        self.assertAlmostEqual(div(50, 200), 25.0)

    def test_div_handles_errors(self) -> None:
        self.assertEqual(div(10, 0), '')
        self.assertEqual(div('a', 10), '')

