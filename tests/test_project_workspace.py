import json
import logging
import os
import struct
import tempfile
import unittest
import zlib

from PIL import Image

import image_grid
import project_io
from state_manager import ProjectState, StateManager


class ProjectWorkspaceTests(unittest.TestCase):
    def test_sheets_keep_independent_thumbnails_and_settings(self):
        manager = StateManager()
        state = manager.get_state()
        state.thumbnail_metadata = [{"id": "first", "timestamp_sec": 1.0}]
        state.settings.num_columns = 3

        second = manager.add_sheet()
        state = manager.get_state()
        state.thumbnail_metadata = [{"id": "second", "timestamp_sec": 2.0}]
        state.settings.num_columns = 7

        manager.switch_sheet(state.sheets[0].id)
        self.assertEqual(manager.get_state().thumbnail_metadata[0]["id"], "first")
        self.assertEqual(manager.get_settings().num_columns, 3)

        manager.switch_sheet(second.id)
        self.assertEqual(manager.get_state().thumbnail_metadata[0]["id"], "second")
        self.assertEqual(manager.get_settings().num_columns, 7)

    def test_json_and_png_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = ProjectState(project_name="Demo", source_paths=["video.mp4"])
            state.thumbnail_metadata = [{"id": "a", "timestamp_sec": 3.25, "hidden": True}]
            state.settings.crop_left = 5.0
            state.settings.thumbnail_aspect_ratio = "16:9"

            json_path = project_io.save_project_json(os.path.join(temp_dir, "demo"), state)
            loaded_json, kind = project_io.load_project(json_path)
            self.assertEqual(kind, "pymovieprint-json")
            self.assertEqual(loaded_json.project_name, "Demo")
            self.assertTrue(loaded_json.thumbnail_metadata[0]["hidden"])

            png_path = os.path.join(temp_dir, "demo.png")
            Image.new("RGB", (40, 30), "red").save(png_path)
            project_io.embed_project_in_png(png_path, state)
            loaded_png, kind = project_io.load_project(png_path)
            self.assertEqual(kind, "pymovieprint-png")
            self.assertEqual(loaded_png.settings.thumbnail_aspect_ratio, "16:9")
            self.assertEqual(loaded_png.thumbnail_metadata[0]["timestamp_sec"], 3.25)

    def test_imports_official_movieprint_text_chunks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            png_path = os.path.join(temp_dir, "official.png")
            Image.new("RGB", (8, 8), "black").save(png_path)
            chunks = project_io._png_text_chunks(png_path)
            self.assertEqual(chunks, {})

            # Insert the same tEXt chunks MoviePrint writes immediately before IEND.
            with open(png_path, "rb") as handle:
                raw = handle.read()
            iend = raw.rfind(b"\x00\x00\x00\x00IEND")
            additions = b""
            for key, value in {
                "filePath": "C%3A%5Cvideo.mp4",
                "columnCount": "4",
                "frameNumberArray": "[10,20,30]",
                "transformObject": '{"rotationFlag":0,"cropTop":0,"cropRight":0,"cropBottom":0,"cropLeft":0}',
            }.items():
                data = key.encode("latin-1") + b"\0" + value.encode("latin-1")
                kind = b"tEXt"
                additions += struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
            with open(png_path, "wb") as handle:
                handle.write(raw[:iend] + additions + raw[iend:])

            state, kind = project_io.load_project(png_path)
            self.assertEqual(kind, "movieprint-png")
            self.assertEqual(state.settings.num_columns, 4)
            self.assertEqual(state.settings.rotate_thumbnails, 90)
            self.assertEqual([item["frame_number"] for item in state.thumbnail_metadata], [10, 20, 30])


class RendererEditingTests(unittest.TestCase):
    def test_hidden_filter_sort_and_antialiased_rounding(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            early = os.path.join(temp_dir, "early.png")
            late = os.path.join(temp_dir, "late.png")
            output = os.path.join(temp_dir, "grid.png")
            Image.new("RGB", (160, 90), "red").save(early)
            Image.new("RGB", (160, 90), "blue").save(late)
            ok, layout = image_grid.create_image_grid(
                image_source_data=[
                    {"image_path": late, "timestamp_sec": 9, "id": "late", "hidden": True},
                    {"image_path": early, "timestamp_sec": 1, "id": "early"},
                ],
                output_path=output,
                columns=2,
                rows=1,
                fit_to_output_params=True,
                output_width=360,
                output_height=120,
                background_color_hex="#101010",
                grid_margin=8,
                padding=8,
                rounded_corners=18,
                filter_mode="visible",
                sort_mode="timestamp",
                logger=logging.getLogger("test_renderer"),
            )
            self.assertTrue(ok)
            self.assertEqual(len(layout), 1)
            self.assertEqual(layout[0]["thumbnail_id"], "early")
            with Image.open(output) as rendered:
                x, y = layout[0]["x"], layout[0]["y"]
                self.assertEqual(rendered.getpixel((x, y)), (16, 16, 16))
                self.assertEqual(rendered.getpixel((x + layout[0]["width"] // 2, y + layout[0]["height"] // 2)), (255, 0, 0))

    def test_crop_and_aspect_helpers_are_safe(self):
        source = Image.new("RGB", (200, 100), "white")
        cropped = image_grid._apply_crop(source, top=10, right=20, bottom=10, left=20)
        self.assertEqual(cropped.size, (120, 80))
        self.assertAlmostEqual(image_grid._aspect_value("16:9"), 16 / 9)
        self.assertIsNone(image_grid._aspect_value("source"))


if __name__ == "__main__":
    unittest.main()
