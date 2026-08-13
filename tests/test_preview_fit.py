import unittest

import movieprint_gui


class PreviewFitTests(unittest.TestCase):
    def test_preview_fit_zoom_contains_image(self):
        cases = [
            ((1920, 1080), (960, 800), 0.5),
            ((1080, 1920), (960, 800), 800 / 1920),
            ((400, 200), (1000, 800), 2.5),
            ((100, 100), (1000, 1000), 5.0),
        ]

        for image_size, viewport_size, expected in cases:
            with self.subTest(image_size=image_size, viewport_size=viewport_size):
                zoom = movieprint_gui.ZoomableCanvas._calculate_fit_zoom(
                    *image_size, *viewport_size
                )

                self.assertAlmostEqual(zoom, expected)
                self.assertLessEqual(image_size[0] * zoom, viewport_size[0])
                self.assertLessEqual(image_size[1] * zoom, viewport_size[1])

    def test_preview_fit_zoom_handles_unlaid_out_viewport(self):
        self.assertEqual(
            movieprint_gui.ZoomableCanvas._calculate_fit_zoom(1920, 1080, 0, 0),
            1.0,
        )
