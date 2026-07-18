import os
import tempfile
import unittest

import cv2
import numpy as np
from PIL import Image

import utils


class ImageOrientationTests(unittest.TestCase):
    def _write_exif_image(self, directory, orientation):
        # Use different colored quadrants so an incorrect transform cannot pass by
        # matching dimensions alone.
        pixels = np.zeros((40, 80, 3), dtype=np.uint8)
        pixels[:20, :40] = (255, 0, 0)
        pixels[:20, 40:] = (0, 255, 0)
        pixels[20:, :40] = (0, 0, 255)
        pixels[20:, 40:] = (255, 255, 0)

        image_path = os.path.join(directory, f'orientation_{orientation}.jpg')
        image = Image.fromarray(pixels, mode='RGB')
        exif = image.getexif()
        exif[274] = orientation
        image.save(image_path, quality=100, subsampling=0, exif=exif)
        return image_path

    def test_all_exif_orientations_match_browser_facing_opencv_result(self):
        with tempfile.TemporaryDirectory(prefix='toolib_exif_test_') as temp_dir:
            for orientation in range(1, 9):
                with self.subTest(orientation=orientation):
                    image_path = self._write_exif_image(temp_dir, orientation)

                    expected = cv2.imread(image_path)
                    actual = utils.imread_with_exif(image_path)

                    self.assertIsNotNone(actual)
                    np.testing.assert_array_equal(expected, actual)

    def test_orientation_6_preserves_grayscale_flag(self):
        with tempfile.TemporaryDirectory(prefix='toolib_exif_test_') as temp_dir:
            image_path = self._write_exif_image(temp_dir, orientation=6)

            expected = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
            actual = utils.imread_with_exif(image_path, cv2.IMREAD_GRAYSCALE)

            self.assertIsNotNone(actual)
            self.assertEqual((80, 40), actual.shape)
            np.testing.assert_array_equal(expected, actual)


if __name__ == '__main__':
    unittest.main()
