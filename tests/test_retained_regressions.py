"""Local checks retained across the branch update."""
import builtins
import logging
import queue
import subprocess
import zlib
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
import movieprint_gui as gui
import movieprint_maker as maker
import video_processing as vp
import image_grid
import project_io

LOG = logging.getLogger(__name__)


def test_manual_timestamp_extraction_filters_changed_in_out_range():
    settings = NS(manual_timestamps=[10, 20, 30], manual_thumbnail_metadata=None,
                  hdr_tonemap=False, hdr_algorithm='hable', frame_format='jpg')
    with patch.object(vp, 'extract_frames_from_timestamps', return_value=(True, [])) as extract:
        maker._extract_frames('clip.mp4', 'frames', settings, 15.0, 25.0, LOG)
    assert extract.call_args.kwargs['timestamps'] == [20.0]


def test_blank_grid_is_reported_as_failure(tmp_path):
    ok, _ = image_grid.create_image_grid(image_source_data=[{'image_path':'missing.jpg'}],
        output_path=str(tmp_path/'out.jpg'), columns=1, rows=1, show_header=False, logger=LOG)
    assert not ok


def test_custom_temp_directories_are_unique_and_cleanable(tmp_path):
    settings = NS(temp_dir=str(tmp_path))
    first, cleanup_a, error_a = maker._setup_temp_directory('a/clip.mp4', settings, LOG)
    second, cleanup_b, error_b = maker._setup_temp_directory('b/clip.mp4', settings, LOG)
    assert not error_a and not error_b
    assert first != second and cleanup_a and cleanup_b


def test_hlg_and_pq_use_distinct_hdr_transfer_filters():
    ex = vp.VideoExtractor.__new__(vp.VideoExtractor)
    ex.logger = LOG
    with patch.object(vp.VideoUtils, 'check_ffmpeg_zscale', return_value=True):
        for transfer in ('arib-std-b67', 'smpte2084'):
            ex._hdr_transfer = transfer
            assert 'tin='+transfer in ex._build_hdr_filter_chain('hable')


def test_scrubber_replaces_queued_value_with_latest_motion():
    handler = gui.ScrubbingHandler.__new__(gui.ScrubbingHandler)
    handler._scrub_queue = queue.Queue(maxsize=1)
    handler._scrub_queue.put_nowait((1.0, 0))
    handler.active = True
    handler.start_x = 0
    handler.original_timestamp = 0
    handler.thumbnail_index = 0
    handler.handle_motion(NS(x=200))
    assert handler._scrub_queue.get_nowait() == (4.0, 0)


def test_preview_edits_only_apply_to_the_previewed_single_video(tmp_path):
    first, other = tmp_path/'previewed.mp4', tmp_path/'other.mp4'
    first.touch()
    other.touch()
    meta = [dict(video_path=str(first), timestamp_sec=10)]
    matches = gui.MoviePrintApp._preview_metadata_matches_single_source
    assert matches([str(first)], meta)
    assert not matches([str(other)], meta)
    assert not matches([str(first), str(other)], meta)


def test_dependency_loader_reports_project_io_import_failure():
    original = builtins.__import__
    def imported(name, *args, **kwargs):
        if name == 'project_io':
            raise RuntimeError('project metadata test failure')
        return original(name, *args, **kwargs)
    class ProbeManager:
        LOAD_FAILURES = []
        MISSING_LIBS = []
    with patch('builtins.__import__', side_effect=imported):
        gui.DependencyManager.load.__func__(ProbeManager)
    assert 'project_io.py (RuntimeError: project metadata test failure)' in ProbeManager.MISSING_LIBS


def test_invalid_saved_gui_settings_are_logged_and_ignored(tmp_path, monkeypatch, caplog):
    path = tmp_path/'settings.json'
    path.write_text('{not valid json')
    monkeypatch.setattr(gui, 'SETTINGS_FILE', str(path))
    app = NS(_loading_persistent_settings=False)
    with caplog.at_level(logging.WARNING):
        gui.MoviePrintApp._load_persistent_settings(app)
    assert not app._loading_persistent_settings
    assert 'Could not load saved GUI settings' in caplog.text


def test_generation_worker_removes_its_temporary_queue_handler():
    app = NS(queue=queue.Queue())
    logger = logging.getLogger('gui_thread_12345')
    old = list(logger.handlers)
    with patch.object(gui.DependencyManager, 'movieprint_maker', return_value=([], [])), \
         patch.object(gui.threading, 'get_ident', return_value=12345):
        gui.MoviePrintApp.run_generation_in_thread(app, NS(), None)
    assert logger.handlers == old


def test_hdr_detection_times_out_instead_of_hanging():
    ex = vp.VideoExtractor.__new__(vp.VideoExtractor)
    ex.video_path, ex._is_hdr_confirmed, ex.logger = 'clip.mp4', None, LOG
    with patch.object(vp.shutil, 'which', return_value='ffprobe'), \
         patch.object(vp.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ffprobe', 10)) as run:
        assert not ex.detect_hdr()
    assert run.call_args.kwargs['timeout'] == 10


def test_frame_export_uses_its_configured_output_directory_for_permission_check(tmp_path):
    video = tmp_path/'source'/'input.mp4'
    video.parent.mkdir()
    video.write_text('video')
    destination = tmp_path/'frames'
    destination.mkdir()
    settings = NS(output_dir=None, start_time=None, end_time=None, output_frames_only=True,
        individual_frames_output_dir=str(destination), overwrite_mode='overwrite', frame_format='jpg')
    frames = [{'frame_path':'frame_000.jpg'}]
    with patch.object(maker.shutil, 'which', return_value='ffmpeg'), \
         patch.object(maker.os, 'access', side_effect=lambda p, mode: str(p) != str(video.parent)), \
         patch.object(maker, '_setup_temp_directory', return_value=(str(tmp_path), False, None)), \
         patch.object(maker, '_extract_frames', return_value=(True, frames)), \
         patch.object(maker, '_apply_exclusions', return_value=(frames, [])), \
         patch.object(maker, '_limit_frames_for_grid', return_value=frames), \
         patch.object(maker, '_process_thumbnails', return_value=frames), \
         patch.object(maker, '_export_individual_frames', return_value=(True, 'out.jpg')):
        ok, result = maker.process_single_video(str(video), settings, 'out.jpg', LOG)
    assert ok and result == 'out.jpg'


def test_compressed_png_project_metadata_cannot_expand_past_limit():
    data = zlib.compress(b'x' * (project_io.MAX_PROJECT_BYTES+1))
    with pytest.raises(ValueError, match='8 MB limit'):
        project_io._bounded_zlib_decompress(data)
