import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import movieprint_maker


class MoviePrintMakerTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test_movieprint_maker")
        self.logger.handlers = []
        self.logger.addHandler(logging.NullHandler())

    def test_parse_time_to_seconds_supported_formats(self):
        self.assertEqual(movieprint_maker.parse_time_to_seconds("75.5"), 75.5)
        self.assertEqual(movieprint_maker.parse_time_to_seconds("01:15.5"), 75.5)
        self.assertEqual(movieprint_maker.parse_time_to_seconds("00:01:15.5"), 75.5)

    def test_parse_time_to_seconds_rejects_invalid(self):
        self.assertIsNone(movieprint_maker.parse_time_to_seconds("-1"))
        self.assertIsNone(movieprint_maker.parse_time_to_seconds("aa:bb"))
        self.assertIsNone(movieprint_maker.parse_time_to_seconds("01:99"))

    def test_discover_video_files_recursive_and_nonrecursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            top_video = os.path.join(tmp, "a.mp4")
            nested_dir = os.path.join(tmp, "nested")
            os.makedirs(nested_dir, exist_ok=True)
            nested_video = os.path.join(nested_dir, "b.mkv")
            not_video = os.path.join(tmp, "note.txt")

            for path in (top_video, nested_video, not_video):
                with open(path, "w", encoding="utf-8") as f:
                    f.write("x")

            non_recursive = movieprint_maker.discover_video_files(
                [tmp], ".mp4,.mkv", recursive_scan=False, logger=self.logger
            )
            recursive = movieprint_maker.discover_video_files(
                [tmp], ".mp4,.mkv", recursive_scan=True, logger=self.logger
            )

            self.assertEqual(non_recursive, [top_video])
            self.assertEqual(recursive, sorted([top_video, nested_video]))

    def test_process_single_video_writes_to_configured_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_video = os.path.join(tmp, "input.mp4")
            temp_frames = os.path.join(tmp, "frames")
            output_dir = os.path.join(tmp, "custom_out")
            os.makedirs(temp_frames, exist_ok=True)
            with open(input_video, "w", encoding="utf-8") as f:
                f.write("video")

            settings = SimpleNamespace(
                output_dir=output_dir,
                start_time=None,
                end_time=None,
                max_output_filesize_kb=None,
                save_metadata_json=False,
                output_frames_only=False,
                overwrite_mode="overwrite",
                individual_frames_output_dir="",
                frame_format="jpg",
                input_paths=[input_video],
            )

            fake_meta = [{"frame_path": os.path.join(temp_frames, "frame_000.jpg"), "timestamp_sec": 1.0}]

            with mock.patch.object(movieprint_maker, "_setup_temp_directory", return_value=(temp_frames, False, None)), \
                 mock.patch.object(movieprint_maker, "_extract_frames", return_value=(True, fake_meta)), \
                 mock.patch.object(movieprint_maker, "_apply_exclusions", return_value=(fake_meta, [])), \
                 mock.patch.object(movieprint_maker, "_limit_frames_for_grid", return_value=fake_meta), \
                 mock.patch.object(movieprint_maker, "_process_thumbnails", return_value=fake_meta), \
                 mock.patch.object(movieprint_maker, "_generate_movieprint", return_value=(True, [], None)), \
                 mock.patch.object(movieprint_maker, "enforce_max_filesize", return_value=None):

                ok, final_path = movieprint_maker.process_single_video(
                    input_video, settings, "out.jpg", self.logger
                )

            self.assertTrue(ok)
            self.assertEqual(final_path, os.path.join(output_dir, "out.jpg"))

    def test_execute_skip_mode_uses_output_dir_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = os.path.join(tmp, "out")
            os.makedirs(output_dir, exist_ok=True)
            video_path = os.path.join(tmp, "clip.mp4")
            with open(video_path, "w", encoding="utf-8") as f:
                f.write("video")

            existing_output = os.path.join(output_dir, "clip_movieprint.jpg")
            with open(existing_output, "w", encoding="utf-8") as f:
                f.write("existing")

            settings = SimpleNamespace(
                input_paths=[video_path],
                video_extensions=".mp4",
                recursive_scan=False,
                frame_format="jpg",
                output_naming_mode="suffix",
                output_filename="",
                output_filename_suffix="_movieprint",
                overwrite_mode="skip",
                output_frames_only=False,
                output_dir=output_dir,
            )

            with mock.patch.object(movieprint_maker, "_ensure_cv2_available", return_value=None), \
                 mock.patch.object(movieprint_maker, "discover_video_files", return_value=[video_path]), \
                 mock.patch.object(movieprint_maker, "process_single_video") as process_mock:
                ok, failed = movieprint_maker.execute_movieprint_generation(settings, self.logger)

            self.assertEqual(ok, [])
            self.assertEqual(failed, [])
            process_mock.assert_not_called()

    def test_load_config_defaults_filters_unknown_keys(self):
        parser = movieprint_maker._build_parser()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"padding": 12, "not_a_real_option": True}, f)

            defaults = movieprint_maker.load_config_defaults(config_path, parser, self.logger)

        self.assertEqual(defaults.get("padding"), 12)
        self.assertNotIn("not_a_real_option", defaults)

    def test_main_can_write_config_template_and_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_video = os.path.join(tmp, "input.mp4")
            with open(input_video, "w", encoding="utf-8") as f:
                f.write("video")

            template_path = os.path.join(tmp, "template.json")
            argv = [
                "movieprint_maker.py",
                input_video,
                tmp,
                "--save_config_template",
                template_path,
            ]
            with mock.patch.object(sys, "argv", argv):
                movieprint_maker.main()

            self.assertTrue(os.path.exists(template_path))
            with open(template_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(data["output_dir"], tmp)
            self.assertEqual(data["input_paths"], [input_video])


if __name__ == "__main__":
    unittest.main()
