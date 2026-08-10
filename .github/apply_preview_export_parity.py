from pathlib import Path
import re
import textwrap

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == '.github' else Path.cwd()


def replace_once(path, old, new, label):
    path = ROOT / path
    with open(path, 'r', encoding='utf-8', newline='') as handle:
        text = handle.read()
    pattern = r'\r?\n'.join(re.escape(line) for line in textwrap.dedent(old).strip('\n').split('\n'))
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {len(matches)}")
    match = matches[0]
    matched = match.group(0)
    eol = '\r\n' if '\r\n' in matched else '\n'
    replacement = textwrap.dedent(new).strip('\n').replace('\n', eol)
    text = text[:match.start()] + replacement + text[match.end():]
    with open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(text)


# movieprint_maker.py: preserve the exact editable thumbnail contract while
# re-extracting source frames at final quality.
replace_once(
    'movieprint_maker.py',
    '''
        return 0.0

    def _extract_frames(video_file_path, temp_dir, settings, start_sec, end_sec, logger, fast_preview=False):
    ''',
    '''
        return 0.0

    def _timestamp_key(value):
        try:
            return round(float(value), 9)
        except (TypeError, ValueError):
            return None

    def _merge_manual_thumbnail_metadata(metadata_list, settings, logger):
        """Restore preview/editor metadata onto freshly extracted final-quality frames."""
        requested_metadata = getattr(settings, 'manual_thumbnail_metadata', None)
        if not requested_metadata:
            return metadata_list

        by_timestamp = {}
        without_timestamp = []
        for extracted in metadata_list:
            key = _timestamp_key(extracted.get('timestamp_sec'))
            if key is None:
                without_timestamp.append(extracted)
            else:
                by_timestamp.setdefault(key, []).append(extracted)

        merged = []
        for requested in requested_metadata:
            if not isinstance(requested, dict):
                continue
            key = _timestamp_key(requested.get('timestamp_sec'))
            candidates = by_timestamp.get(key, []) if key is not None else []
            if candidates:
                extracted = candidates.pop(0)
            elif without_timestamp:
                extracted = without_timestamp.pop(0)
            else:
                logger.warning(
                    "  Final extraction did not return the preview thumbnail at %r.",
                    requested.get('timestamp_sec'),
                )
                continue

            combined = dict(extracted)
            for field, value in requested.items():
                if field in {'frame_path', 'video_path', 'video_filename'}:
                    continue
                combined[field] = value

            # The final-quality extraction owns physical source information.
            for field in ('frame_path', 'video_path', 'video_filename', 'timestamp_sec', 'frame_number'):
                if field in extracted:
                    combined[field] = extracted[field]
            merged.append(combined)

        leftovers = [item for values in by_timestamp.values() for item in values]
        leftovers.extend(without_timestamp)
        if leftovers:
            logger.warning(
                "  %d final frame(s) had no matching preview metadata; preserving them at the end.",
                len(leftovers),
            )
            merged.extend(leftovers)
        return merged

    def _extract_frames(video_file_path, temp_dir, settings, start_sec, end_sec, logger, fast_preview=False):
    ''',
    'insert render metadata merge helpers',
)

replace_once(
    'movieprint_maker.py',
    '''
        if hasattr(settings, 'manual_timestamps') and settings.manual_timestamps:
            logger.info(f"  Using {len(settings.manual_timestamps)} manual timestamps provided by GUI.")
            return video_processing.extract_frames_from_timestamps(
                video_path=video_file_path, 
                timestamps=settings.manual_timestamps, 
                output_folder=temp_dir, 
                logger=logger, 
                output_format=settings.frame_format,
                fast_preview=fast_preview,
                hdr_tonemap=hdr_tonemap,
                hdr_algorithm=hdr_algo
            )
    ''',
    '''
        if hasattr(settings, 'manual_timestamps') and settings.manual_timestamps:
            logger.info(f"  Using {len(settings.manual_timestamps)} manual timestamps provided by GUI.")
            success, extracted = video_processing.extract_frames_from_timestamps(
                video_path=video_file_path,
                timestamps=settings.manual_timestamps,
                output_folder=temp_dir,
                logger=logger,
                output_format=settings.frame_format,
                fast_preview=fast_preview,
                hdr_tonemap=hdr_tonemap,
                hdr_algorithm=hdr_algo
            )
            if success and extracted:
                extracted = _merge_manual_thumbnail_metadata(extracted, settings, logger)
            return success, extracted
    ''',
    'merge manual metadata after high-quality extraction',
)

replace_once(
    'movieprint_maker.py',
    '''
        items_for_grid = []
        if settings.layout_mode == "timeline":
            items_for_grid = [{'image_path': sm['frame_path'],
                               'width_ratio': float(sm.get('duration_frames', 1.0)),
                               'timestamp_sec': sm.get('timestamp_sec'),
                               'frame_number': sm.get('frame_number'),
                               'video_filename': sm.get('video_filename'),
                               'video_path': sm.get('video_path')}
                              for sm in metadata_list if sm.get('duration_frames', 0) > 0]
        else:
            items_for_grid = [{'image_path': meta['frame_path'],
                               'timestamp_sec': meta.get('timestamp_sec'),
                               'frame_number': meta.get('frame_number'),
                               'video_filename': meta.get('video_filename'),
                               'video_path': meta.get('video_path')}
                              for meta in metadata_list]
    ''',
    '''
        items_for_grid = []
        for meta in metadata_list:
            if settings.layout_mode == "timeline" and float(meta.get('duration_frames') or 0) <= 0:
                continue
            item = dict(meta)
            item['image_path'] = meta['frame_path']
            if settings.layout_mode == "timeline":
                item['width_ratio'] = float(meta.get('duration_frames') or 1.0)
            items_for_grid.append(item)
    ''',
    'forward per-thumbnail render metadata to image_grid',
)

replace_once(
    'movieprint_maker.py',
    '''
                has_transform = any((
                    getattr(settings, 'crop_top', 0.0),
                    getattr(settings, 'crop_right', 0.0),
                    getattr(settings, 'crop_bottom', 0.0),
                    getattr(settings, 'crop_left', 0.0),
                    getattr(settings, 'rotate_thumbnails', 0),
                    getattr(settings, 'thumbnail_aspect_ratio', 'source') != 'source',
                ))
                if not has_transform:
                    shutil.copy2(source_path, target_path)
                else:
                    with Image.open(source_path) as source_image:
                        transformed = image_grid._apply_crop(
                            source_image,
                            getattr(settings, 'crop_top', 0.0),
                            getattr(settings, 'crop_right', 0.0),
                            getattr(settings, 'crop_bottom', 0.0),
                            getattr(settings, 'crop_left', 0.0),
                        )
                        transformed = image_grid._apply_rotation(
                            transformed, getattr(settings, 'rotate_thumbnails', 0)
                        )
                        aspect = image_grid._aspect_value(
                            getattr(settings, 'thumbnail_aspect_ratio', 'source')
                        )
                        if aspect:
                            target_w = transformed.width
                            target_h = max(1, round(target_w / aspect))
                            if target_h > transformed.height:
                                target_h = transformed.height
                                target_w = max(1, round(target_h * aspect))
                            transformed = ImageOps.fit(
                                transformed, (target_w, target_h), method=Image.Resampling.LANCZOS
                            )
                        save_kwargs = (
                            {'quality': getattr(settings, 'output_quality', 95)}
                            if frame_format in {'jpg', 'jpeg'} else {}
                        )
                        transformed.convert('RGB').save(target_path, **save_kwargs)
    ''',
    '''
                item_transform = meta.get('transform') if isinstance(meta.get('transform'), dict) else {}
                item_aspect = meta.get('aspect_ratio') or getattr(settings, 'thumbnail_aspect_ratio', 'source')
                has_transform = bool(item_transform) or any((
                    getattr(settings, 'crop_top', 0.0),
                    getattr(settings, 'crop_right', 0.0),
                    getattr(settings, 'crop_bottom', 0.0),
                    getattr(settings, 'crop_left', 0.0),
                    getattr(settings, 'rotate_thumbnails', 0),
                    item_aspect != 'source',
                ))
                if not has_transform:
                    shutil.copy2(source_path, target_path)
                else:
                    with Image.open(source_path) as source_image:
                        transform_config = image_grid.GridConfig(
                            output_path=target_path,
                            rotation=getattr(settings, 'rotate_thumbnails', 0),
                            crop_top=getattr(settings, 'crop_top', 0.0),
                            crop_right=getattr(settings, 'crop_right', 0.0),
                            crop_bottom=getattr(settings, 'crop_bottom', 0.0),
                            crop_left=getattr(settings, 'crop_left', 0.0),
                            thumbnail_aspect_ratio=getattr(settings, 'thumbnail_aspect_ratio', 'source'),
                        )
                        transformed = image_grid._apply_source_transform(source_image, meta, transform_config)
                        aspect = image_grid._aspect_value(
                            meta.get('aspect_ratio', transform_config.thumbnail_aspect_ratio)
                        )
                        if aspect:
                            target_w = transformed.width
                            target_h = max(1, round(target_w / aspect))
                            if target_h > transformed.height:
                                target_h = transformed.height
                                target_w = max(1, round(target_h * aspect))
                            transformed = ImageOps.fit(
                                transformed, (target_w, target_h), method=Image.Resampling.LANCZOS
                            )
                        save_kwargs = (
                            {'quality': getattr(settings, 'output_quality', 95)}
                            if frame_format in {'jpg', 'jpeg'} else {}
                        )
                        transformed.convert('RGB').save(target_path, **save_kwargs)
    ''',
    'honour per-thumbnail transforms in individual frame export',
)

# movieprint_gui.py: carry the editable preview contract into final generation
# and ensure the preview uses the same overlay settings as the final renderer.
replace_once(
    'movieprint_gui.py',
    '''
        import argparse
        import threading
    ''',
    '''
        import argparse
        import copy
        import threading
    ''',
    'import copy for render metadata snapshots',
)

for label, old, new in [
    (
        'restore preview frame-info parity',
        '''
                    'frame_info_show': settings.frame_info_show,
                    'layout_mode': settings.layout_mode,
        ''',
        '''
                    'frame_info_show': settings.frame_info_show,
                    'frame_info_timecode_or_frame': settings.frame_info_timecode_or_frame,
                    'frame_info_font_color': settings.frame_info_font_color,
                    'frame_info_bg_color': settings.frame_info_bg_color,
                    'frame_info_position': settings.frame_info_position,
                    'frame_info_size': settings.frame_info_size,
                    'frame_info_margin': settings.frame_info_margin,
                    'layout_mode': settings.layout_mode,
        ''',
    ),
    (
        'initial preview settings parity',
        '''
                    'frame_info_show': self.frame_info_show_var.get(),
                    'preview_quality': int(self.preview_quality_var.get()),
        ''',
        '''
                    'frame_info_show': self.frame_info_show_var.get(),
                    'frame_info_timecode_or_frame': self.frame_info_timecode_or_frame_var.get(),
                    'frame_info_font_color': self.frame_info_font_color_var.get(),
                    'frame_info_bg_color': self.frame_info_bg_color_var.get(),
                    'frame_info_position': self.frame_info_position_var.get(),
                    'frame_info_size': int(self.frame_info_size_var.get()),
                    'frame_info_margin': int(self.frame_info_margin_var.get()),
                    'preview_quality': int(self.preview_quality_var.get()),
        ''',
    ),
    (
        'initial preview renderer parity',
        '''
                        frame_info_show=config['frame_info_show'],
                        quality=config['preview_quality'],
        ''',
        '''
                        frame_info_show=config['frame_info_show'],
                        frame_info_timecode_or_frame=config['frame_info_timecode_or_frame'],
                        frame_info_font_color=config['frame_info_font_color'],
                        frame_info_bg_color=config['frame_info_bg_color'],
                        frame_info_position=config['frame_info_position'],
                        frame_info_size=config['frame_info_size'],
                        frame_info_margin=config['frame_info_margin'],
                        quality=config['preview_quality'],
        ''',
    ),
    (
        'quick refresh renderer parity',
        '''
                frame_info_show=self.frame_info_show_var.get(),
                quality=int(self.preview_quality_var.get()),
        ''',
        '''
                frame_info_show=self.frame_info_show_var.get(),
                frame_info_timecode_or_frame=self.frame_info_timecode_or_frame_var.get(),
                frame_info_font_color=self.frame_info_font_color_var.get(),
                frame_info_bg_color=self.frame_info_bg_color_var.get(),
                frame_info_position=self.frame_info_position_var.get(),
                frame_info_size=int(self.frame_info_size_var.get()),
                frame_info_margin=int(self.frame_info_margin_var.get()),
                quality=int(self.preview_quality_var.get()),
        ''',
    ),
]:
    replace_once('movieprint_gui.py', old, new, label)

replace_once(
    'movieprint_gui.py',
    '''
            def _grid_transform_params(self):
                return {
                    'crop_top': float(self.crop_top_var.get() or 0),
                    'crop_right': float(self.crop_right_var.get() or 0),
                    'crop_bottom': float(self.crop_bottom_var.get() or 0),
                    'crop_left': float(self.crop_left_var.get() or 0),
                    'thumbnail_aspect_ratio': self.thumbnail_aspect_ratio_var.get(),
                    'sort_mode': self.sort_mode_var.get(),
                    'filter_mode': self.filter_mode_var.get(),
                }

            # --- PROJECT WORKSPACE ---
    ''',
    '''
            def _grid_transform_params(self):
                return {
                    'crop_top': float(self.crop_top_var.get() or 0),
                    'crop_right': float(self.crop_right_var.get() or 0),
                    'crop_bottom': float(self.crop_bottom_var.get() or 0),
                    'crop_left': float(self.crop_left_var.get() or 0),
                    'thumbnail_aspect_ratio': self.thumbnail_aspect_ratio_var.get(),
                    'sort_mode': self.sort_mode_var.get(),
                    'filter_mode': self.filter_mode_var.get(),
                }

            @staticmethod
            def _snapshot_render_metadata(metadata):
                """Copy editable thumbnail state without reusing low-resolution preview files."""
                snapshots = []
                for item in metadata or []:
                    snapshot = copy.deepcopy(item)
                    snapshot.pop('frame_path', None)
                    snapshots.append(snapshot)
                return snapshots

            # --- PROJECT WORKSPACE ---
    ''',
    'add render metadata snapshot helper',
)

replace_once(
    'movieprint_gui.py',
    '''
                            faces = face_cascade.detectMultiScale(gray, 1.1, 4)
                            if len(faces) > 0:
                                for (x, y, w, h) in faces:
                                    cv2.rectangle(img, (x, y), (x+w, y+h), (0, 255, 0), 2)
                                cv2.imwrite(item['frame_path'], img)
    ''',
    '''
                            faces = face_cascade.detectMultiScale(gray, 1.1, 4)
                            item['face_detection'] = {
                                'num_faces': len(faces),
                                'face_bboxes_thumbnail': [list(map(int, face)) for face in faces],
                            }
    ''',
    'stop preview face detection from drawing export-only green boxes',
)

replace_once(
    'movieprint_gui.py',
    '''
                rows = int(self.num_rows_var.get())
                cols = int(self.num_columns_var.get())
                settings.manual_timestamps = None
                
                if settings.layout_mode == "grid":
                    settings.rows = rows
                    settings.columns = cols
                    settings.max_frames_for_print = rows * cols
                    settings.target_row_height = None
                    settings.interval_seconds = None
                    if active_tab == "Single Source":
                        current_meta = self._metadata_in_display_order()
                        if current_meta:
                            settings.manual_timestamps = [m.get('timestamp_sec', 0.0) for m in current_meta]
                    else:
                        settings.manual_timestamps = None
                else:
                    settings.rows = None
                    settings.columns = None
                    settings.max_frames_for_print = None
                    settings.target_row_height = int(self.target_row_height_var.get() or 150)
                    settings.interval_seconds = None
                    if active_tab == "Single Source":
                        current_meta = self._metadata_in_display_order()
                        if current_meta:
                            settings.manual_timestamps = [m.get('timestamp_sec', 0.0) for m in current_meta]
    ''',
    '''
                rows = int(self.num_rows_var.get())
                cols = int(self.num_columns_var.get())
                settings.manual_timestamps = None
                settings.manual_thumbnail_metadata = None

                if settings.layout_mode == "grid":
                    settings.rows = rows
                    settings.columns = cols
                    settings.max_frames_for_print = rows * cols
                    settings.target_row_height = None
                    settings.interval_seconds = None
                else:
                    settings.rows = None
                    settings.columns = None
                    settings.max_frames_for_print = None
                    settings.target_row_height = int(self.target_row_height_var.get() or 150)
                    settings.interval_seconds = None

                if active_tab == "Single Source":
                    current_meta = self._metadata_in_display_order()
                    if current_meta:
                        settings.manual_timestamps = [
                            float(item.get('timestamp_sec') or 0.0) for item in current_meta
                        ]
                        settings.manual_thumbnail_metadata = self._snapshot_render_metadata(current_meta)
    ''',
    'send exact editable thumbnail metadata to final generation',
)

TEST_FILE = r'''import logging
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
'''
(ROOT / 'tests' / 'test_preview_export_parity.py').write_text(TEST_FILE, encoding='utf-8', newline='\n')

print('Preview/export parity patch applied successfully.')
