import re
from pathlib import Path

from django.test import SimpleTestCase

APP_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_ICON = re.compile(r'\bbi-[a-z]')


class NoBootstrapIconsTest(SimpleTestCase):
    def test_templates_and_python_have_no_bootstrap_icons(self) -> None:
        offenders = [
            f'{path.relative_to(APP_ROOT)}:{number}'
            for pattern in ('*.html', '*.py')
            for path in APP_ROOT.rglob(pattern)
            for number, line in enumerate(
                path.read_text(encoding='utf-8').splitlines(),
                start=1,
            )
            if BOOTSTRAP_ICON.search(line)
        ]
        self.assertEqual(offenders, [])
