import unittest
from movieprint_gui import MoviePrintApp
from version import __version__

class TestMoviePrintApp(unittest.TestCase):
    def test_app_initialization(self):
        """
        Tests if the main application window initializes correctly.
        """
        app = None
        try:
            app = MoviePrintApp()
            self.assertIsNotNone(app.root)
            self.assertEqual(app.root.title(), f"MoviePrint Generator v{__version__}")
        finally:
            if app:
                app.root.destroy()

if __name__ == '__main__':
    unittest.main()
