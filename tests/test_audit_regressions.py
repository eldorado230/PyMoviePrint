import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

import image_grid
import movieprint_gui
import movieprint_maker
import video_processing


class _Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Widget:
    def pack(self, *args, **kwargs):
        return None

    def pack_forget(self):
        return None


class AuditRegressionTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test_audit_regressions")
        self.logger.handlers = []
        self.logger.addHandler(logging.NullHandler())

    def test_grid_timestamp_extraction_respects_requested_range(self):
        settings = SimpleNamespace(
            hdr_tonemap=False,
            hdr_algorithm="hable",
            manual_timestamps=None,
            layout_mode="grid",
            columns=2,
            rows=2,
            frame_format="jpg",
            use_gpu=False,
            extraction_mode="interval",
            interval_seconds=None,
            interval_frames=None,
            shot_threshold=27.0,
        )

        with mock.patch.object(movieprint_maker, "_get_video_duration", return_value=100.0), \
             mock.patch.object(
                 movieprint_maker.video_processing,
                 "extract_frames_from_timestamps",
                 return_value=(True, []),
             ) as extract_mock:
            movieprint_maker._extract_frames(
                "clip.mp4", "frames", settings, 40.0, 50.0, self.logger
            )

        timestamps = extract_mock.call_args.kwargs["timestamps"]
        self.assertEqual(timestamps, [42.0, 44.0, 46.0, 48.0])

    def test_interval_frame_command_defaults_start_and_sets_vsync_as_output_option(self):
        extractor = video_processing.VideoExtractor.__new__(video_processing.VideoExtractor)
        extractor.video_path = "clip.mp4"
        extractor.logger = self.logger

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(
                 video_processing.VideoExtractor,
                 "properties",
                 new_callable=mock.PropertyMock,
                 return_value=(30.0, 60.0, 1800),
             ), \
             mock.patch.object(video_processing.shutil, "which", return_value="ffmpeg"), \
             mock.patch.object(
                 video_processing.VideoUtils,
                 "run_ffmpeg_command",
                 return_value=False,
             ) as run_mock:
            extractor.extract_via_ffmpeg(tmp, interval_frames=30)

        command = run_mock.call_args.args[0]
        self.assertEqual(command[command.index("-ss") + 1], "0.0")
        filter_value = command[command.index("-vf") + 1]
        self.assertIn("select='not(mod(n,30))'", filter_value)
        self.assertNotIn("vsync", filter_value)
        self.assertEqual(command[command.index("-vsync") + 1], "vfr")

    def test_cli_returns_failure_exit_code(self):
        argv = ["movieprint_maker.py", "clip.mp4", "out", "--columns", "2", "--rows", "2"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(
                 movieprint_maker,
                 "execute_movieprint_generation",
                 return_value=([], [{"video": "clip.mp4", "reason": "failed"}]),
             ):
            self.assertEqual(movieprint_maker.main(), 1)

    def test_documented_fixed_output_defaults_to_five_rows(self):
        captured = {}

        def fake_execute(settings, logger, progress_callback=None, fast_preview=False):
            captured["settings"] = settings
            return [], []

        argv = [
            "movieprint_maker.py",
            "clip.mp4",
            "out",
            "--fit_to_output_params",
            "--output_width",
            "1920",
            "--output_height",
            "1080",
        ]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(movieprint_maker, "execute_movieprint_generation", side_effect=fake_execute):
            self.assertEqual(movieprint_maker.main(), 0)

        self.assertEqual(captured["settings"].rows, 5)

    def test_cli_can_disable_header_and_overlay_details(self):
        captured = {}

        def fake_execute(settings, logger, progress_callback=None, fast_preview=False):
            captured["settings"] = settings
            return [], []

        argv = [
            "movieprint_maker.py",
            "clip.mp4",
            "out",
            "--columns",
            "2",
            "--rows",
            "2",
            "--hide_file_path",
            "--hide_timecode",
            "--hide_frame_num",
        ]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(movieprint_maker, "execute_movieprint_generation", side_effect=fake_execute):
            self.assertEqual(movieprint_maker.main(), 0)

        settings = captured["settings"]
        self.assertFalse(settings.show_file_path)
        self.assertFalse(settings.show_timecode)
        self.assertFalse(settings.show_frame_num)

    def test_fixed_grid_infers_rows_when_interval_mode_supplies_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.jpg")
            output = os.path.join(tmp, "grid.jpg")
            Image.new("RGB", (100, 50), "red").save(source)

            ok, _ = image_grid.create_image_grid(
                image_source_data=[{"image_path": source}] * 3,
                output_path=output,
                columns=2,
                rows=None,
                fit_to_output_params=True,
                output_width=640,
                output_height=360,
                show_header=False,
                logger=self.logger,
            )

            self.assertTrue(ok)
            with Image.open(output) as result:
                self.assertEqual(result.size, (640, 360))

    def test_fixed_timeline_honors_requested_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.jpg")
            output = os.path.join(tmp, "timeline.jpg")
            Image.new("RGB", (100, 50), "blue").save(source)

            ok, _ = image_grid.create_image_grid(
                image_source_data=[{"image_path": source, "width_ratio": 1}],
                output_path=output,
                layout_mode="timeline",
                fit_to_output_params=True,
                output_width=640,
                output_height=360,
                target_row_height=100,
                show_header=False,
                logger=self.logger,
            )

            self.assertTrue(ok)
            with Image.open(output) as result:
                self.assertEqual(result.size, (640, 360))

    def test_frame_export_failure_preserves_previous_generated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = os.path.join(tmp, "frames")
            os.makedirs(output_dir)
            old_frame = os.path.join(output_dir, "frame_0001_1p0s.jpg")
            source = os.path.join(tmp, "source.jpg")
            Path(old_frame).write_bytes(b"old")
            Path(source).write_bytes(b"new")

            with mock.patch.object(movieprint_maker.shutil, "copy2", side_effect=OSError("disk full")):
                ok, error = movieprint_maker._export_individual_frames(
                    [{"frame_path": source, "timestamp_sec": 1.0}],
                    output_dir,
                    SimpleNamespace(frame_format="jpg"),
                    self.logger,
                )

            self.assertFalse(ok)
            self.assertIn("disk full", error)
            self.assertEqual(Path(old_frame).read_bytes(), b"old")

    def test_frame_export_replaces_generated_files_and_preserves_unrelated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = os.path.join(tmp, "frames")
            os.makedirs(output_dir)
            old_frame = os.path.join(output_dir, "frame_0001_1p0s.jpg")
            notes = os.path.join(output_dir, "notes.txt")
            source = os.path.join(tmp, "source.jpg")
            Path(old_frame).write_bytes(b"old")
            Path(notes).write_text("keep", encoding="utf-8")
            Path(source).write_bytes(b"new")

            ok, result = movieprint_maker._export_individual_frames(
                [{"frame_path": source, "timestamp_sec": 1.0}],
                output_dir,
                SimpleNamespace(frame_format="jpg"),
                self.logger,
            )

            self.assertTrue(ok)
            self.assertEqual(result, os.path.abspath(output_dir))
            self.assertEqual(Path(old_frame).read_bytes(), b"new")
            self.assertEqual(Path(notes).read_text(encoding="utf-8"), "keep")

    def test_preview_processing_does_not_mutate_images_for_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.jpg")
            Image.new("RGB", (80, 40), "green").save(source)
            app = SimpleNamespace(queue=SimpleNamespace(put=lambda *args: None))

            movieprint_gui.MoviePrintApp._process_preview_thumbnails(
                app,
                [{"frame_path": source}],
                {"rotate_thumbnails": 90, "detect_faces": False},
                self.logger,
            )

            with Image.open(source) as image:
                self.assertEqual(image.size, (80, 40))

    def test_fixed_name_mode_accepts_persisted_internal_value(self):
        app = SimpleNamespace(
            output_naming_mode_var=_Variable("custom"),
            naming_mode_display_var=_Variable("Add Suffix"),
            lbl_suffix=_Widget(),
            entry_suffix=_Widget(),
            lbl_custom=_Widget(),
            entry_custom=_Widget(),
        )

        movieprint_gui.MoviePrintApp._toggle_naming_inputs(app, "custom")

        self.assertEqual(app.output_naming_mode_var.get(), "custom")
        self.assertEqual(app.naming_mode_display_var.get(), "Fixed Name")

    def test_overlay_flags_control_header_and_frame_label(self):
        config = image_grid.GridConfig(
            output_path="unused.jpg",
            header_title="clip.mp4",
            font_settings=image_grid.FontConfig(
                show_file_path=False,
                show_timecode=False,
                show_frame_num=False,
                frame_info_type="timecode",
            ),
        )

        metadata = {"video_path": os.path.abspath("clip.mp4")}
        self.assertEqual(image_grid._header_text("clip.mp4", metadata, config), "clip.mp4")
        config.font_settings.show_file_path = True
        self.assertEqual(
            image_grid._header_text("clip.mp4", metadata, config),
            os.path.abspath("clip.mp4"),
        )
        self.assertEqual(
            image_grid._frame_info_label({"timestamp_sec": 1.0}, 0, config.font_settings),
            "",
        )


if __name__ == "__main__":
    unittest.main()
