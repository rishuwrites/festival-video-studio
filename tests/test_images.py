import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "recap"))

import images


class ImageProviderPriorityTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new("RGB", (640, 640), color="purple")

    def test_deepai_is_first_provider_for_scene_and_thumbnail_images(self):
        providers = ("_cloudflare", "_flux", "_pollinations")
        for generator in (images.generate, images.generate_thumbnail):
            with self.subTest(generator=generator.__name__), tempfile.TemporaryDirectory() as temp_dir:
                output = Path(temp_dir) / "image.jpg"
                with mock.patch.object(images, "_deepai", return_value=self.image) as deepai, \
                        mock.patch.multiple(
                            images,
                            **{name: mock.DEFAULT for name in providers},
                        ) as fallbacks:
                    self.assertTrue(generator("test image", 1, str(output)))

                deepai.assert_called_once()
                for fallback in fallbacks.values():
                    fallback.assert_not_called()
                self.assertTrue(output.is_file())

    def test_deepai_block_falls_back_to_cloudflare(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "image.jpg"
            with mock.patch.object(
                images, "_deepai", side_effect=images.DeepAIUnavailableError("CAPTCHA detected"),
            ), mock.patch.object(images, "_cloudflare", return_value=self.image) as cloudflare:
                self.assertTrue(images.generate("test image", 1, str(output)))
            self.assertTrue(output.is_file())
        cloudflare.assert_called_once()

    def test_captcha_and_rate_limit_errors_are_not_retried(self):
        for message in ("CAPTCHA detected", "verify you are human", "rate limit"):
            with self.subTest(message=message):
                self.assertFalse(images._retryable_image_error(RuntimeError(message)))


if __name__ == "__main__":
    unittest.main()
