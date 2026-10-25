import re
from pathlib import Path

from django.test import SimpleTestCase

APP_ROOT = Path(__file__).resolve().parents[2]
ESBUILD_CONFIG = APP_ROOT.parent / 'esbuild.config.mjs'
BUNDLE_REFERENCE = re.compile(r'js/dist/([\w/-]+)\.js')
ENTRY_POINT = re.compile(r"'?([\w/-]+)'?:\s*'static/js/")


class JsBundlesTest(SimpleTestCase):
    def test_referenced_bundles_are_esbuild_entry_points(self) -> None:
        config = ESBUILD_CONFIG.read_text(encoding='utf-8')
        entry_points = set(ENTRY_POINT.findall(config))
        missing = sorted(
            f'{path.relative_to(APP_ROOT.parent)}: {name}'
            for path in APP_ROOT.rglob('*.html')
            for name in BUNDLE_REFERENCE.findall(
                path.read_text(encoding='utf-8'),
            )
            if name not in entry_points
        )
        self.assertEqual(missing, [])
