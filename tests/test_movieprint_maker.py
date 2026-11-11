import logging
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

import image_grid
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

    def test_discover_video_files_deduplicates_overlapping_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "clip.mp4")
            with open(video, "w", encoding="utf-8") as f:
                f.write("video")

            discovered = movieprint_maker.discover_video_files(
                [tmp, video], ".mp4", recursive_scan=True, logger=self.logger
            )

            self.assertEqual(discovered, [video])

    def test_fixed_name_batch_allows_unique_source_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_dir = os.path.join(tmp, "Movie One")
            second_dir = os.path.join(tmp, "Movie Two")
            os.makedirs(first_dir, exist_ok=True)
            os.makedirs(second_dir, exist_ok=True)
            first_video = os.path.join(first_dir, "movie.mkv")
            second_video = os.path.join(second_dir, "movie.mkv")

            for path in (first_video, second_video):
                with open(path, "w", encoding="utf-8") as f:
                    f.write("video")

            settings = SimpleNamespace(
                frame_format="jpg",
                output_naming_mode="custom",
                output_filename="movieprint",
                output_dir=None,
                output_frames_only=False,
                individual_frames_output_dir="",
            )

            videos = movieprint_maker.discover_video_files(
                [tmp], ".mp4,.mkv", recursive_scan=True, logger=self.logger
            )
            collisions = movieprint_maker.find_output_path_collisions(videos, settings)
            outputs = [movieprint_maker.get_target_output_path(video, settings) for video in videos]

            self.assertEqual(collisions, [])
            self.assertEqual({os.path.basename(output) for output in outputs}, {"movieprint.jpg"})
            self.assertEqual(len({os.path.dirname(output) for output in outputs}), 2)

    def test_fixed_name_batch_detects_same_folder_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_video = os.path.join(tmp, "part1.mp4")
            second_video = os.path.join(tmp, "part2.mkv")

            for path in (first_video, second_video):
                with open(path, "w", encoding="utf-8") as f:
                    f.write("video")

            settings = SimpleNamespace(
                frame_format="jpg",
                output_naming_mode="custom",
                output_filename="movieprint",
                output_dir=None,
                output_frames_only=False,
                individual_frames_output_dir="",
            )

            videos = movieprint_maker.discover_video_files(
                [tmp], ".mp4,.mkv", recursive_scan=False, logger=self.logger
            )
            collisions = movieprint_maker.find_output_path_collisions(videos, settings)

            self.assertEqual(len(collisions), 1)
            self.assertEqual(os.path.basename(collisions[0]["output"]), "movieprint.jpg")
            self.assertEqual(set(collisions[0]["videos"]), {first_video, second_video})

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

            with mock.patch.object(movieprint_maker.video_processing.shutil, "which", return_value="ffmpeg"), \
                 mock.patch.object(movieprint_maker, "_setup_temp_directory", return_value=(temp_frames, False, None)), \
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

    def test_execute_skip_mode_uses_existing_frame_export_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            video_path = os.path.join(tmp, "clip.mp4")
            with open(video_path, "w", encoding="utf-8") as f:
                f.write("video")
            os.makedirs(os.path.join(tmp, "clip_movieprint_frames"), exist_ok=True)

            settings = SimpleNamespace(
                input_paths=[video_path], video_extensions=".mp4", recursive_scan=False,
                frame_format="jpg", output_naming_mode="suffix", output_filename="",
                output_filename_suffix="_movieprint", overwrite_mode="skip",
                output_frames_only=True, output_dir=None, individual_frames_output_dir="",
            )

            with mock.patch.object(movieprint_maker, "_ensure_cv2_available", return_value=None), \
                 mock.patch.object(movieprint_maker, "process_single_video") as process_mock:
                successful, failed = movieprint_maker.execute_movieprint_generation(settings, self.logger)

            self.assertEqual(successful, [])
            self.assertEqual(failed, [])
            process_mock.assert_not_called()

    def test_execute_blocks_colliding_outputs_without_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = os.path.join(tmp, "part1.mp4")
            second = os.path.join(tmp, "part2.mp4")
            for path in (first, second):
                with open(path, "w", encoding="utf-8") as f:
                    f.write("video")

            settings = SimpleNamespace(
                input_paths=[tmp], video_extensions=".mp4", recursive_scan=False,
                frame_format="jpg", output_naming_mode="custom", output_filename="movieprint",
                overwrite_mode="overwrite", output_frames_only=False, output_dir=None,
                individual_frames_output_dir="",
            )

            with mock.patch.object(movieprint_maker, "_ensure_cv2_available", return_value=None), \
                 mock.patch.object(movieprint_maker, "process_single_video") as process_mock:
                successful, failed = movieprint_maker.execute_movieprint_generation(settings, self.logger)

            self.assertEqual(successful, [])
            self.assertEqual({entry["video"] for entry in failed}, {first, second})
            self.assertTrue(all("collision" in entry["reason"] for entry in failed))
            process_mock.assert_not_called()

    def test_execute_cancellation_stops_before_processing_next_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            video_path = os.path.join(tmp, "clip.mp4")
            with open(video_path, "w", encoding="utf-8") as f:
                f.write("video")
            cancel_event = threading.Event()
            cancel_event.set()
            settings = SimpleNamespace(
                input_paths=[video_path], video_extensions=".mp4", recursive_scan=False,
                frame_format="jpg", output_naming_mode="suffix", output_filename="",
                output_filename_suffix="_movieprint", overwrite_mode="overwrite",
                output_frames_only=False, output_dir=None, individual_frames_output_dir="",
                cancel_event=cancel_event,
            )

            with mock.patch.object(movieprint_maker, "_ensure_cv2_available", return_value=None), \
                 mock.patch.object(movieprint_maker, "process_single_video") as process_mock:
                successful, failed = movieprint_maker.execute_movieprint_generation(settings, self.logger)

            self.assertEqual(successful, [])
            self.assertEqual(failed, [])
            self.assertTrue(settings.cancelled)
            process_mock.assert_not_called()

    def test_execute_reports_invalid_custom_name_per_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            video_path = os.path.join(tmp, "clip.mp4")
            with open(video_path, "w", encoding="utf-8") as f:
                f.write("video")
            settings = SimpleNamespace(
                input_paths=[video_path], video_extensions=".mp4", recursive_scan=False,
                frame_format="jpg", output_naming_mode="custom", output_filename="nested/name",
                overwrite_mode="overwrite", output_frames_only=False, output_dir=None,
                individual_frames_output_dir="",
            )

            with mock.patch.object(movieprint_maker, "_ensure_cv2_available", return_value=None):
                successful, failed = movieprint_maker.execute_movieprint_generation(settings, self.logger)

            self.assertEqual(successful, [])
            self.assertEqual(failed[0]["video"], video_path)
            self.assertIn("plain filename", failed[0]["reason"])

    def test_execute_reports_missing_ffmpeg_for_each_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            video_path = os.path.join(tmp, "clip.mp4")
            with open(video_path, "w", encoding="utf-8") as f:
                f.write("video")
            settings = SimpleNamespace(
                input_paths=[video_path], video_extensions=".mp4", recursive_scan=False,
                frame_format="jpg", output_naming_mode="suffix", output_filename="",
                output_filename_suffix="_movieprint", overwrite_mode="overwrite",
                output_frames_only=False, output_dir=None, individual_frames_output_dir="",
            )

            with mock.patch.object(movieprint_maker, "_ensure_cv2_available", return_value=None), \
                 mock.patch.object(movieprint_maker.video_processing.shutil, "which", return_value=None):
                successful, failed = movieprint_maker.execute_movieprint_generation(settings, self.logger)

            self.assertEqual(successful, [])
            self.assertEqual(failed[0]["video"], video_path)
            self.assertIn("FFmpeg was not found", failed[0]["reason"])

    def test_custom_name_rejects_windows_folder_components(self):
        settings = SimpleNamespace(
            frame_format="jpg",
            output_naming_mode="custom",
            output_filename=r"C:\\movieprints\\movieprint",
        )

        with self.assertRaisesRegex(ValueError, "plain filename"):
            movieprint_maker.get_effective_output_filename(r"C:\\Movies\\clip.mp4", settings)

    def test_limit_frames_for_grid_allows_single_selection(self):
        metadata = [
            {"frame_path": f"frame_{idx:03d}.jpg", "timestamp_sec": float(idx)}
            for idx in range(4)
        ]
        settings = SimpleNamespace(
            layout_mode="grid",
            max_frames_for_print=1,
            frame_format="jpg",
        )

        selected = movieprint_maker._limit_frames_for_grid(
            metadata, settings, temp_dir="", cleanup_temp=False, logger=self.logger
        )

        self.assertEqual(selected, [metadata[0]])

    def test_generate_timeline_movieprint_uses_output_width(self):
        settings = SimpleNamespace(
            layout_mode="timeline",
            padding=5,
            background_color="#111111",
            grid_margin=0,
            rounded_corners=0,
            frame_info_show=False,
            show_header=False,
            show_file_path=True,
            show_timecode=True,
            show_frame_num=True,
            frame_info_timecode_or_frame="timecode",
            frame_info_font_color="#FFFFFF",
            frame_info_bg_color="#000000",
            frame_info_position="bottom_left",
            frame_info_size=10,
            frame_info_margin=5,
            output_quality=95,
            fit_to_output_params=False,
            output_width=1280,
            output_height=720,
            target_row_height=120,
        )
        metadata = [{
            "frame_path": "shot_001.jpg",
            "duration_frames": 42,
            "timestamp_sec": 1.5,
            "frame_number": 36,
            "video_filename": "clip.mp4",
        }]

        with mock.patch.object(movieprint_maker.image_grid, "create_image_grid", return_value=(True, [])) as create_mock:
            ok, layout_data, error = movieprint_maker._generate_movieprint(
                metadata, settings, "out.jpg", self.logger
            )

        self.assertTrue(ok)
        self.assertEqual(layout_data, [])
        self.assertIsNone(error)
        create_kwargs = create_mock.call_args.kwargs
        self.assertEqual(create_kwargs["output_width"], 1280)
        self.assertNotIn("max_grid_width", create_kwargs)

    def test_timeline_layout_uses_width_ratio(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = os.path.join(tmp, "first.jpg")
            second = os.path.join(tmp, "second.jpg")
            output = os.path.join(tmp, "timeline.jpg")

            Image.new("RGB", (100, 50), "red").save(first)
            Image.new("RGB", (100, 50), "blue").save(second)

            ok, layout_data = image_grid.create_image_grid(
                image_source_data=[
                    {"image_path": first, "width_ratio": 1, "timestamp_sec": 1.0},
                    {"image_path": second, "width_ratio": 4, "timestamp_sec": 2.0},
                ],
                output_path=output,
                layout_mode="timeline",
                target_row_height=40,
                output_width=500,
                padding=0,
                show_header=False,
                frame_info_show=True,
            )

            self.assertTrue(ok)
            self.assertTrue(os.path.exists(output))
            self.assertGreater(layout_data[1]["width"], layout_data[0]["width"])


if __name__ == "__main__":
    unittest.main()
