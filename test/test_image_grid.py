import unittest
import os
import shutil
from PIL import Image
from image_grid import create_image_grid
import logging

class TestImageGrid(unittest.TestCase):
    def setUp(self):
        self.test_dir = "test_images"
        os.makedirs(self.test_dir, exist_ok=True)
        self.image_paths = []
        for i in range(5):
            path = os.path.join(self.test_dir, f"test_image_{i}.png")
            img = Image.new('RGB', (100, 100), color = 'red')
            img.save(path)
            self.image_paths.append(path)
        self.output_path = "test_output.png"
        self.logger = logging.getLogger()

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        os.remove(self.output_path)

    def test_create_image_grid(self):
        success, _ = create_image_grid(self.image_paths, self.output_path, 5, self.logger, columns=3)
        self.assertTrue(success)
        self.assertTrue(os.path.exists(self.output_path))

if __name__ == '__main__':
    unittest.main()
