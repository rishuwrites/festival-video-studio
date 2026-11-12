import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "recap"))

import render


class ThumbnailRenderingTests(unittest.TestCase):
    def test_thumbnail_has_readable_resolution_and_burns_in_hindi_headline(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "art.jpg"
            first = Path(folder) / "thumbnail-first.jpg"
            second = Path(folder) / "thumbnail-second.jpg"

            art = Image.new("RGB", (1600, 900), (42, 95, 125))
            draw = ImageDraw.Draw(art)
            draw.ellipse((980, 100, 1500, 620), fill=(240, 160, 45))
            art.save(source)

            with mock.patch.object(render, "font", side_effect=lambda size: ImageFont.truetype(render._fp(), size)):
                render.thumbnail(str(source), "छठ कब है?", "छठ पूजा", "भारत | 2026", str(first))
                render.thumbnail(str(source), "छठ क्यों खास है?", "छठ पूजा", "भारत | 2026", str(second))

            with Image.open(first) as thumbnail:
                self.assertEqual(thumbnail.size, (1280, 720))
            with Image.open(first) as one, Image.open(second) as two:
                self.assertIsNotNone(ImageChops.difference(one, two).getbbox())

    def test_font_requires_raqm_for_correct_devanagari_shaping(self):
        render.font.cache_clear()
        with mock.patch.object(render.features, "check", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "without RAQM"):
                render.font(48)
        render.font.cache_clear()


if __name__ == "__main__":
    unittest.main()
