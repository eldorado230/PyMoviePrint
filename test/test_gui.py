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
            self.assertIsNotNone(app)
            self.assertEqual(app.title(), f"PyMoviePrint Generator v{__version__}")
        finally:
            if app:
                app.destroy()

if __name__ == '__main__':
    unittest.main()
