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

    def test_festival_name_is_prominent_in_the_thumbnail(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "art.jpg"
            festival = Path(folder) / "festival.jpg"
            alternate = Path(folder) / "alternate.jpg"
            Image.new("RGB", (1600, 900), (110, 75, 35)).save(source)

            with mock.patch.object(render, "font", side_effect=lambda size: ImageFont.truetype(render._fp(), size)):
                render.thumbnail(str(source), "उषा अर्घ्य 2026", "छठ पूजा", "16 नवंबर 2026", str(festival))
                render.thumbnail(str(source), "उषा अर्घ्य 2026", "दिवाली", "16 नवंबर 2026", str(alternate))

            with Image.open(festival) as one, Image.open(alternate) as two:
                self.assertIsNotNone(ImageChops.difference(one, two).getbbox())

    def test_opaque_text_panel_hides_letters_in_generated_artwork(self):
        with tempfile.TemporaryDirectory() as folder:
            clean_source = Path(folder) / "clean.jpg"
            lettered_source = Path(folder) / "lettered.jpg"
            clean_output = Path(folder) / "clean-thumbnail.jpg"
            lettered_output = Path(folder) / "lettered-thumbnail.jpg"
            background = Image.new("RGB", (1600, 900), (42, 95, 125))
            background.save(clean_source)
            lettered = background.copy()
            ImageDraw.Draw(lettered).text(
                (80, 120), "FESTIVAL", font=ImageFont.load_default(), fill=(255, 255, 255),
            )
            lettered.save(lettered_source)

            with mock.patch.object(render, "font", side_effect=lambda size: ImageFont.truetype(render._fp(), size)):
                render.thumbnail(str(clean_source), "पर्व कब है?", "पर्व का नाम", "भारत | 2026", str(clean_output))
                render.thumbnail(str(lettered_source), "पर्व कब है?", "पर्व का नाम", "भारत | 2026", str(lettered_output))

            with Image.open(clean_output) as clean, Image.open(lettered_output) as lettered:
                clean_panel = clean.crop((40, 40, 800, 680))
                lettered_panel = lettered.crop((40, 40, 800, 680))
                self.assertIsNone(ImageChops.difference(clean_panel, lettered_panel).getbbox())

    def test_font_requires_raqm_for_correct_devanagari_shaping(self):
        render.font.cache_clear()
        with mock.patch.object(render.features, "check", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "without RAQM"):
                render.font(48)
        render.font.cache_clear()


if __name__ == "__main__":
    unittest.main()
