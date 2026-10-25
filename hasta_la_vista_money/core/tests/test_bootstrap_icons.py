import re
from pathlib import Path

from django.test import SimpleTestCase

APP_ROOT = Path(__file__).resolve().parents[2]
JS_ROOT = APP_ROOT.parent / 'static' / 'js'
BOOTSTRAP_ICON = re.compile(r'\bbi-[a-z]')


def _offenders(paths: list[Path]) -> list[str]:
    return [
        f'{path.relative_to(APP_ROOT.parent)}:{number}'
        for path in paths
        for number, line in enumerate(
            path.read_text(encoding='utf-8').splitlines(),
            start=1,
        )
        if BOOTSTRAP_ICON.search(line)
    ]


class NoBootstrapIconsTest(SimpleTestCase):
    def test_templates_and_python_have_no_bootstrap_icons(self) -> None:
        paths = [
            path
            for pattern in ('*.html', '*.py')
            for path in APP_ROOT.rglob(pattern)
        ]
        self.assertEqual(_offenders(paths), [])

    def test_js_has_no_bootstrap_icons(self) -> None:
        paths = [
            path
            for path in JS_ROOT.glob('*.js')
            if not path.name.endswith('.min.js')
        ]
        self.assertEqual(_offenders(paths), [])
