import unittest
import os
import shutil
import tempfile
import image_grid
from PIL import Image
import logging

class TestMoviePrintMaker(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_gui_priority_bug(self):
        # GUI sends both rows and columns.
        # If we have fewer images than rows*columns, we expect 'columns' to be respected
        # (maintaining grid width), rather than 'rows' (maintaining grid height/aspect).

        # Setup: 10 images.
        # Request: 5 Cols, 5 Rows.
        # Current behavior (Bug): 10 / 5 (rows) = 2 Cols. Result: 2 cols x 5 rows.
        # Expected behavior (Fix): 5 Cols (explicitly set). Result: 5 cols x 2 rows.

        img_paths = []
        for i in range(10):
            p = os.path.join(self.test_dir, f"dummy_{i}.jpg")
            Image.new('RGB', (10, 10)).save(p)
            img_paths.append(p)

        logger = logging.getLogger("test")

        grid_out = os.path.join(self.test_dir, "grid_priority_test.jpg")

        # Direct call simulating GUI passing both columns and rows
        success, layout = image_grid.create_image_grid(
            image_source_data=img_paths,
            output_path=grid_out,
            padding=0,
            logger=logger,
            layout_mode="grid",
            columns=5,
            rows=5,
            background_color_hex="#FFFFFF"
        )

        self.assertTrue(success)

        # Verify dimensions
        # 5 cols * 10px = 50px width.
        # 2 rows * 10px = 20px height.

        # If bug exists (rows priority logic in image_grid):
        # columns = ceil(10/5) = 2.
        # 2 cols * 10px = 20px width.
        # 5 rows * 10px = 50px height.

        with Image.open(grid_out) as img:
            print(f"Priority Test: Width={img.width}, Height={img.height}")
            self.assertEqual(img.width, 50, f"Grid width should correspond to 5 columns (50px). Got {img.width}")
            self.assertEqual(img.height, 20, f"Grid height should correspond to 2 rows (20px). Got {img.height}")

if __name__ == '__main__':
    unittest.main()
