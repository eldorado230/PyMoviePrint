import unittest
import tkinter as tk
from unittest.mock import patch
from movieprint_gui import MoviePrintApp

class TestMoviePrintApp(unittest.TestCase):

    @patch('tkinter.messagebox')
    def test_reset_all_settings(self, mock_messagebox):
        # Mock the askyesno to always return True
        mock_messagebox.askyesno.return_value = True

        app = MoviePrintApp()

        # Change some settings from their defaults
        app.input_paths_var.set("/some/test/path")
        app._internal_input_paths = ["/some/test/path"]
        app.output_dir_var.set("/some/output/path")
        app.num_columns_var.set("10")
        app.padding_var.set("20")

        # Confirm they are changed
        self.assertEqual(app.input_paths_var.get(), "/some/test/path")
        self.assertEqual(app._internal_input_paths, ["/some/test/path"])
        self.assertEqual(app.output_dir_var.get(), "/some/output/path")
        self.assertEqual(app.num_columns_var.get(), "10")
        self.assertEqual(app.padding_var.get(), "20")

        # Perform the reset
        app.confirm_reset_all_settings()

        # Check that path settings are PRESERVED
        self.assertEqual(app.input_paths_var.get(), "/some/test/path")
        self.assertEqual(app._internal_input_paths, ["/some/test/path"])
        self.assertEqual(app.output_dir_var.get(), "/some/output/path")

        # Check that other settings are reset to their default values
        self.assertEqual(app.num_columns_var.get(), app.default_settings["num_columns_var"])
        self.assertEqual(app.padding_var.get(), app.default_settings["padding_var"])

        # Destroy the app window to prevent the test from hanging
        app.root.destroy()

if __name__ == '__main__':
    unittest.main()