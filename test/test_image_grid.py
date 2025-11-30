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
        if os.path.exists(self.output_path):
            os.remove(self.output_path)

    def test_create_image_grid(self):
        # Update the call to use keyword arguments as per the new docstring/implementation
        success, _ = create_image_grid(
            image_source_data=self.image_paths,
            output_path=self.output_path,
            padding=5,
            logger=self.logger,
            columns=3,
            layout_mode="grid"
        )
        self.assertTrue(success)
        self.assertTrue(os.path.exists(self.output_path))

if __name__ == '__main__':
    unittest.main()
