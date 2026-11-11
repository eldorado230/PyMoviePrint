import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import movieprint_maker


class FrameExportSafetyTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test_frame_export_safety")
        self.logger.handlers = []
        self.logger.addHandler(logging.NullHandler())

    def test_clear_generated_frames_preserves_unrelated_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            generated_jpg = os.path.join(tmp, "frame_0001.jpg")
            generated_png = os.path.join(tmp, "frame_0002_1p25s.png")
            unrelated_file = os.path.join(tmp, "notes.txt")
            unrelated_folder = os.path.join(tmp, "archive")
            nested_frame = os.path.join(unrelated_folder, "frame_0003.jpg")

            os.makedirs(unrelated_folder)

            for path in (
                generated_jpg,
                generated_png,
                unrelated_file,
                nested_frame,
            ):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("test")

            ok, error = movieprint_maker._clear_generated_frame_files(
                tmp, self.logger
            )

            self.assertTrue(ok)
            self.assertIsNone(error)
            self.assertFalse(os.path.exists(generated_jpg))
            self.assertFalse(os.path.exists(generated_png))
            self.assertTrue(os.path.exists(unrelated_file))
            self.assertTrue(os.path.isdir(unrelated_folder))
            self.assertTrue(os.path.exists(nested_frame))

    def test_clear_generated_frames_rejects_file_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "clip_movieprint_frames")

            with open(target, "w", encoding="utf-8") as handle:
                handle.write("not a folder")

            ok, error = movieprint_maker._clear_generated_frame_files(
                target, self.logger
            )

            self.assertFalse(ok)
            self.assertIn("not a folder", error)
            self.assertTrue(os.path.isfile(target))

    def test_clear_generated_frames_reports_delete_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            generated = os.path.join(tmp, "frame_0001.jpg")

            with open(generated, "w", encoding="utf-8") as handle:
                handle.write("test")

            with mock.patch.object(
                movieprint_maker.os,
                "remove",
                side_effect=OSError("file is locked"),
            ):
                ok, error = movieprint_maker._clear_generated_frame_files(
                    tmp, self.logger
                )

            self.assertFalse(ok)
            self.assertIn("file is locked", error)
            self.assertTrue(os.path.exists(generated))


if __name__ == "__main__":
    unittest.main()
