import logging
import os
import tempfile
from types import SimpleNamespace
from unittest import mock

from PIL import Image

import movieprint_gui
import movieprint_maker


def _base_render_settings(**overrides):
    values = dict(
        padding=4,
        background_color="#000000",
        layout_mode="grid",
        grid_margin=2,
        rounded_corners=0,
        rotate_thumbnails=0,
        crop_top=0.0,
        crop_right=0.0,
        crop_bottom=0.0,
        crop_left=0.0,
        thumbnail_aspect_ratio="source",
        sort_mode="manual",
        filter_mode="visible",
        frame_info_show=False,
        show_header=False,
        show_file_path=False,
        show_timecode=False,
        show_frame_num=False,
        frame_info_timecode_or_frame="timecode",
        frame_info_font_color="#FFFFFF",
        frame_info_bg_color="#000000",
        frame_info_position="bottom_left",
        frame_info_size=10,
        frame_info_margin=5,
        output_quality=95,
        fit_to_output_params=False,
        output_width=1920,
        output_height=1080,
        rows=1,
        columns=2,
        target_thumbnail_width=None,
        target_row_height=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_manual_final_extraction_restores_preview_order_and_transform():
    settings = SimpleNamespace(
        manual_timestamps=[8.0, 2.0],
        manual_thumbnail_metadata=[
            {"id": "late", "timestamp_sec": 8.0, "transform": {"rotation": 90}, "duration_frames": 50},
            {"id": "early", "timestamp_sec": 2.0, "transform": {"crop_left": 12.0}, "duration_frames": 25},
        ],
        frame_format="jpg",
        hdr_tonemap=False,
        hdr_algorithm="hable",
    )
    extracted = [
        {"frame_path": "early-full.jpg", "timestamp_sec": 2.0, "frame_number": 50, "video_path": "movie.mkv", "video_filename": "movie.mkv"},
        {"frame_path": "late-full.jpg", "timestamp_sec": 8.0, "frame_number": 200, "video_path": "movie.mkv", "video_filename": "movie.mkv"},
    ]
    with mock.patch.object(movieprint_maker.video_processing, "extract_frames_from_timestamps", return_value=(True, extracted)):
        ok, result = movieprint_maker._extract_frames(
            "movie.mkv", "tmp", settings, None, None, logging.getLogger("test"), fast_preview=False
        )

    assert ok is True
    assert [item["id"] for item in result] == ["late", "early"]
    assert [item["frame_path"] for item in result] == ["late-full.jpg", "early-full.jpg"]
    assert result[0]["transform"] == {"rotation": 90}
    assert result[1]["transform"] == {"crop_left": 12.0}
    assert [item["duration_frames"] for item in result] == [50, 25]


def test_generate_movieprint_forwards_per_thumbnail_metadata():
    metadata = [
        {
            "frame_path": "frame.jpg",
            "timestamp_sec": 4.0,
            "frame_number": 100,
            "video_filename": "movie.mkv",
            "video_path": "movie.mkv",
            "id": "thumb-a",
            "transform": {"rotation": 270, "crop_top": 7.5},
            "aspect_ratio": "1:1",
        }
    ]
    settings = _base_render_settings(columns=1)
    with mock.patch.object(movieprint_maker.image_grid, "create_image_grid", return_value=(True, [])) as create_grid:
        success, _, error = movieprint_maker._generate_movieprint(metadata, settings, "out.jpg", logging.getLogger("test"))

    assert success is True
    assert error is None
    item = create_grid.call_args.kwargs["image_source_data"][0]
    assert item["id"] == "thumb-a"
    assert item["transform"] == {"rotation": 270, "crop_top": 7.5}
    assert item["aspect_ratio"] == "1:1"
    assert item["image_path"] == "frame.jpg"


def test_individual_frame_export_uses_same_per_thumbnail_transform_contract():
    with tempfile.TemporaryDirectory() as tmp:
        source_path = os.path.join(tmp, "source.png")
        output_dir = os.path.join(tmp, "frames")
        Image.new("RGB", (100, 50), "white").save(source_path)
        settings = _base_render_settings(frame_format="png")
        metadata = [{
            "frame_path": source_path,
            "timestamp_sec": 1.0,
            "transform": {"crop_left": 40.0, "rotation": 90},
        }]

        ok, _ = movieprint_maker._export_individual_frames(metadata, output_dir, settings, logging.getLogger("test"))
        assert ok is True
        exported = os.path.join(output_dir, "frame_0001_1p0s.png")
        with Image.open(exported) as image:
            assert image.size == (50, 60)


def test_gui_snapshot_keeps_edit_state_but_not_preview_frame_path():
    source = [{
        "id": "thumb-a",
        "frame_path": "480px-preview.jpg",
        "timestamp_sec": 3.5,
        "transform": {"rotation": 90},
    }]
    snapshot = movieprint_gui.MoviePrintApp._snapshot_render_metadata(source)
    assert snapshot == [{"id": "thumb-a", "timestamp_sec": 3.5, "transform": {"rotation": 90}}]
    snapshot[0]["transform"]["rotation"] = 180
    assert source[0]["transform"]["rotation"] == 90
