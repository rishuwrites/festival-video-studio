import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

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

            render.thumbnail(str(source), "छठ कब है?", "पर्व विशेष", "भारत | 2026", str(first))
            render.thumbnail(str(source), "छठ क्यों खास है?", "पर्व विशेष", "भारत | 2026", str(second))

            with Image.open(first) as thumbnail:
                self.assertEqual(thumbnail.size, (1280, 720))
            with Image.open(first) as one, Image.open(second) as two:
                self.assertIsNotNone(ImageChops.difference(one, two).getbbox())


if __name__ == "__main__":
    unittest.main()
