"""High DPI icons retain source detail and cover physical output pixels."""

import atexit
import copy
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QImage, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication
from shortcut_app.icon_theme import themed_icon_source


class HighDpiRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        hook = sys.excepthook
        import shortcut_app.application as shortcut
        atexit.unregister(shortcut._restore_desktop_icons_safe)
        sys.excepthook = hook
        cls.module = shortcut
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        effects = patch.multiple(self.module.Shortcut, apply_layer=lambda owner: None,
                                 start_backdrop=lambda owner: None, refresh_backdrop=lambda owner: None)
        effects.start()
        self.addCleanup(effects.stop)
        cfg = copy.deepcopy(self.module.DEFAULT_CONFIG)
        cfg.update(theme='light', running_dots=False)
        self.window = self.module.Shortcut(cfg, preview=True)
        self.addCleanup(self.dispose)

    def dispose(self):
        self.window.shutdown_presentation()
        self.window.deleteLater()
        self.app.processEvents()

    def test_native_sources_retain_full_resolution_for_default_and_large_icons(self):
        source = themed_icon_source('apps')
        self.assertEqual(source.width(), 512)
        self.assertEqual(self.window._category_artwork({'id': 'apps', 'icon': 'apps'}).cacheKey(), source.cacheKey())
        self.assertEqual(self.window._settings_artwork().cacheKey(), themed_icon_source('utilities').cacheKey())
        self.assertEqual(next(item for item in self.window.items if item.get('computer'))['pixmap'].width(), 512)

    def test_125_150_200_and_300_percent_output_matches_direct_source_resampling(self):
        source = themed_icon_source('apps')
        item = {'pixmap': source}
        for ratio in (1.0, 1.25, 1.5, 2.0, 3.0):
            for logical_size in (39.0, 52.0, 73.4):
                with self.subTest(ratio=ratio, size=logical_size), \
                        patch.object(self.window, 'devicePixelRatioF', return_value=ratio):
                    pixmap = self.window.icon_scaled(item, logical_size)
                    pixels = round(logical_size * ratio)
                    self.assertEqual(pixmap.width(), pixels)
                    self.assertEqual(pixmap.devicePixelRatioF(), ratio)
                    expected = source.scaled(pixels, pixels, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                    expected.setDevicePixelRatio(ratio)
                    self.assertEqual(pixmap.toImage(), expected.toImage())

    def test_fractional_positions_land_on_output_pixels_and_use_full_detail(self):
        item = {'pixmap': themed_icon_source('apps')}
        for ratio in (1.25, 1.5, 2.0):
            with self.subTest(ratio=ratio), patch.object(self.window, 'devicePixelRatioF', return_value=ratio):
                rect = self.window.pixel_aligned_rect(QRectF(3.27, 4.13, 52.3, 52.3))
                for coordinate in (rect.x(), rect.y(), rect.width(), rect.height()):
                    self.assertAlmostEqual(coordinate * ratio, round(coordinate * ratio))
                pixmap = self.window.icon_scaled(item, rect.width())
                target = QPixmap(pixmap.size())
                target.setDevicePixelRatio(ratio)
                target.fill(Qt.transparent)
                painter = QPainter(target)
                painter.setRenderHint(QPainter.SmoothPixmapTransform)
                painter.drawPixmap(QRectF(0, 0, rect.width(), rect.height()), pixmap, QRectF(pixmap.rect()))
                painter.end()
                self.assertEqual(target.toImage(), pixmap.toImage())

    def test_same_pixel_count_on_different_screens_does_not_reuse_wrong_density(self):
        item = {'pixmap': themed_icon_source('apps')}
        with patch.object(self.window, 'devicePixelRatioF', return_value=1.0):
            first = self.window.icon_scaled(item, 78)
        with patch.object(self.window, 'devicePixelRatioF', return_value=1.5):
            second = self.window.icon_scaled(item, 52)
        self.assertEqual(first.width(), second.width())
        self.assertEqual(first.devicePixelRatioF(), 1.0)
        self.assertEqual(second.devicePixelRatioF(), 1.5)
        self.assertEqual(item['pixmap'].devicePixelRatioF(), 1.0)

    def test_content_image_retains_256_pixel_native_detail(self):
        image = QImage(256, 256, QImage.Format_ARGB32)
        image.fill(Qt.white)
        self.assertEqual(self.module.normalize_entry_image(image).size(), image.size())


if __name__ == '__main__':
    unittest.main()
