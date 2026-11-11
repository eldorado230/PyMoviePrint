import logging
import os
import queue
import threading
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, Mock, patch

import numpy as np
from PIL import Image
import pytest

import image_grid
import movieprint_gui as gui
import movieprint_maker as maker
import project_io
import state_manager as sm
import video_processing as vp

LOG = logging.getLogger('studio_tests')


def test_cached_frame_size_preserves_layout_geometry(tmp_path):
    source = tmp_path/'source.jpg'
    Image.new('RGB', (800, 400), 'blue').save(source)
    meta = [dict(frame_path=str(source), timestamp_sec=0)]
    ok, original = image_grid.create_image_grid(image_source_data=[dict(image_path=str(source))],
        output_path=str(tmp_path/'before.jpg'), columns=1, rows=1, show_header=False, logger=LOG)
    assert ok
    app = NS(queue=queue.Queue())
    gui.MoviePrintApp._process_preview_thumbnails(app, meta,
        dict(detect_faces=False, cache_max_width=200), LOG)
    with Image.open(source) as image:
        assert image.size == (200, 100)
    ok, resized = image_grid.create_image_grid(image_source_data=[dict(meta[0], image_path=str(source))],
        output_path=str(tmp_path/'after.jpg'), columns=1, rows=1, show_header=False, logger=LOG)
    assert ok
    assert [(i['width'], i['height']) for i in resized] == [(i['width'], i['height']) for i in original]


def test_header_timeline_renders(tmp_path):
    source = tmp_path/'source.png'
    Image.new('RGB', (160, 90)).save(source)
    for mode in ('grid', 'timeline'):
        ok, layout = image_grid.create_image_grid(image_source_data=[dict(image_path=str(source), timestamp_sec=1)],
            output_path=str(tmp_path/f'{mode}.png'), layout_mode=mode, columns=1, rows=1,
            show_header=True, show_header_timeline=True, logger=LOG)
        assert ok and layout


def test_naming_tokens_are_contained():
    settings = NS(output_naming_mode='custom', output_filename='{movie}_{sheet}.png', sheet_name='Cuts')
    assert maker.get_effective_output_filename('C:/video/My Film.mp4', settings) == 'My Film_Cuts.png'
    settings.sheet_name = '../escape'
    with pytest.raises(ValueError):
        maker.get_effective_output_filename('clip.mp4', settings)


def test_time_scaled_timeline_splits_scenes(tmp_path):
    source = tmp_path/'source.png'
    Image.new('RGB', (100, 100), 'red').save(source)
    ok, layout = image_grid.create_image_grid(image_source_data=[dict(image_path=str(source),
        scene_start_sec=0, scene_end_sec=90)], output_path=str(tmp_path/'timeline.png'),
        layout_mode='timeline', timeline_minutes_per_row=1, output_width=616,
        target_row_height=100, grid_margin=8, padding=8, show_header=False, logger=LOG)
    assert ok and len(layout) == 2
    assert layout[0]['width'] == 600
    assert layout[1]['width'] == 300


def test_reflow_keeps_all_manual_frames(tmp_path):
    metadata = [dict(timestamp_sec=i) for i in range(4)]
    settings = NS(manual_timestamps=[0, 1, 2, 3], layout_mode='grid', max_frames_for_print=1)
    assert maker._limit_frames_for_grid(metadata, settings, str(tmp_path), False, LOG) == metadata


def test_partial_render_preserves_existing_output(tmp_path):
    source = tmp_path / 'ok.png'
    Image.new('RGB', (10, 10)).save(source)
    for mode in ('grid', 'timeline'):
        target = tmp_path / f'{mode}.png'
        target.write_bytes(b'old output')
        ok, _ = image_grid.create_image_grid(
            image_source_data=[str(source), str(tmp_path/'missing.png')], output_path=str(target), layout_mode=mode,
            columns=2, rows=1, logger=LOG)
        assert not ok
        assert target.read_bytes() == b'old output'


def test_combined_frames_collisions_detected():
    settings = NS(output_dir=None, output_naming_mode='custom', output_filename='same.jpg',
                  include_individual_frames=True, output_frames_only=False,
                  individual_frames_output_dir='C:/shared_frames')
    collisions = maker.find_output_path_collisions(['C:/one/a.mp4', 'C:/two/b.mp4'], settings)
    assert len(collisions) == 1
    assert len(collisions[0]['videos']) == 2


def test_skip_allows_existing_shared_output_but_overwrite_blocks_it(tmp_path):
    first, second = tmp_path / 'one.mp4', tmp_path / 'two.mp4'
    first.touch()
    second.touch()
    target = tmp_path / 'fanart.jpg'
    target.write_bytes(b'existing')
    settings = NS(output_dir=str(tmp_path), output_naming_mode='custom', output_filename='fanart',
                  frame_format='jpg', output_frames_only=False, overwrite_mode='skip')
    assert maker.find_output_path_collisions([str(first), str(second)], settings) == []
    settings.overwrite_mode = 'overwrite'
    assert len(maker.find_output_path_collisions([str(first), str(second)], settings)) == 1
    target.unlink()
    settings.overwrite_mode = 'skip'
    assert len(maker.find_output_path_collisions([str(first), str(second)], settings)) == 1


def test_timestamp_extraction_reports_partial_failure():
    with patch.object(vp, 'VideoExtractor') as cls:
        extractor = cls.return_value.__enter__.return_value
        extractor.detect_hdr.return_value = False
        extractor.extract_timestamps_optimized.return_value = [{'timestamp_sec': 1}]
        ok, result = vp.extract_frames_from_timestamps('a.mp4', [1, 2], 'temp', LOG)
        assert not ok and len(result) == 1


def test_recovery_never_substitutes_another_existing_source(tmp_path):
    a = tmp_path/'a.mp4'
    a.touch()
    state = sm.ProjectState(source_paths=[str(a), str(tmp_path/'missing.mp4')])
    state.thumbnail_metadata = [dict(video_path=str(a), timestamp_sec=1),
                                dict(video_path=str(tmp_path/'missing.mp4'), timestamp_sec=2)]
    state.sync_active_sheet()
    app = NS(preview_temp_dir=None, temp_dirs_to_cleanup=[])
    with patch.object(gui.filedialog, 'askopenfilename', return_value='') as picker:
        with pytest.raises(ValueError):
            gui.MoviePrintApp._prepare_loaded_project_frames(app, state)
    assert 'missing.mp4' in picker.call_args.kwargs['title']
    assert state.thumbnail_metadata[1]['video_path'].endswith('missing.mp4')


def test_suffix_cannot_escape():
    for suffix in ['/../../escape', '\\..\\escape', ':stream']:
        with pytest.raises(ValueError):
            maker.get_effective_output_filename('clip.mp4', NS(output_filename_suffix=suffix))


@pytest.mark.parametrize('name', ['evil.png:stream', 'CON.jpg', 'NUL.extra.png', '../escape.png', '..\\escape.png'])
def test_windows_unsafe_custom_names_rejected(name):
    with pytest.raises(ValueError):
        maker.get_effective_output_filename('clip.mp4', NS(output_naming_mode='custom', output_filename=name))


def test_atomic_image_failure_preserves_previous(tmp_path):
    path = tmp_path / 'out.png'
    path.write_bytes(b'original')
    im = Image.new('RGB', (10, 10))
    def fail(target, **kwargs):
        with open(target, 'wb') as stream:
            stream.write(b'partial')
        raise OSError('disk full')
    with patch.object(im, 'save', side_effect=fail):
        assert not image_grid._save_image_optimized(im, str(path), 90, LOG)
    assert path.read_bytes() == b'original'
    assert list(tmp_path.iterdir()) == [path]


def test_timeline_requires_rendered_frames(tmp_path):
    source = tmp_path / 'source.png'
    Image.new('RGB', (10, 10)).save(source)
    with patch.object(image_grid, '_apply_source_transform', side_effect=ValueError('bad transform')):
        ok, layout = image_grid.create_image_grid(image_source_data=[{'image_path': str(source)}],
            output_path=str(tmp_path / 'out.png'), layout_mode='timeline', show_header=False)
    assert not ok and not layout


def test_sheet_names_unique_after_delete():
    manager = sm.StateManager()
    second = manager.add_sheet().id
    manager.add_sheet()
    manager.switch_sheet(second)
    manager.remove_active_sheet()
    manager.add_sheet()
    names = [s.name for s in manager.get_state().sheets]
    assert len(names) == len(set(names))


def test_invalid_active_id_falls_back():
    state = sm.ProjectState.from_dict({'sheets': [{'id': 'valid'}], 'active_sheet_id': 'absent'})
    assert state.active_sheet_id == 'valid'
    with pytest.raises(ValueError):
        sm.ProjectState.from_dict({'sheets': [{'thumbnail_metadata': None}]})


def test_scrub_keeps_original_pixels_and_undo(tmp_path):
    path = tmp_path / 'frame.jpg'
    Image.new('RGB', (5, 5), 'red').save(path)
    manager = sm.StateManager()
    manager.replace_state(sm.ProjectState(thumbnail_metadata=[{'frame_path': str(path), 'timestamp_sec': 1}]))
    manager.add_sheet(duplicate_active=True)
    manager.snapshot()
    app = NS(state_manager=manager, preview_zoomable_canvas=NS(original_image=None), _refresh_selected_inspector=lambda: None)
    gui.MoviePrintApp.update_thumbnail_in_preview(app, 0, Image.new('RGB', (5, 5), 'blue'), 2)
    assert manager.get_state().thumbnail_metadata[0]['frame_path'] != str(path)
    manager.undo()
    with Image.open(manager.get_state().thumbnail_metadata[0]['frame_path']) as im:
        assert im.getpixel((0, 0))[0] > 240


def test_png_completion_preserves_output_source(tmp_path):
    path = tmp_path / 'B.png'
    Image.new('RGB', (5, 5)).save(path)
    project_io.embed_project_in_png(str(path), sm.ProjectState(source_paths=['B.mp4']))
    app = NS(state_manager=sm.StateManager(), status_lbl=Mock())
    with patch.object(gui.messagebox, 'showinfo'):
        gui.MoviePrintApp._handle_generation_done(app, {'successful_ops': [{'output': str(path)}]})
    assert project_io.load_project(str(path))[0].source_paths == ['B.mp4']


def test_grid_shot_dispatch():
    settings = NS(layout_mode='grid', rows=2, columns=2, extraction_mode='shot',
                  shot_threshold=27, frame_format='jpg')
    with patch.object(vp, 'extract_shot_boundary_frames', return_value=(True, [])) as extract:
        maker._extract_frames('clip.mp4', 'unused', settings, None, None, LOG)
    assert extract.called


def test_cancel_last_video_is_reported():
    settings = NS(input_paths=['clip.mp4'], cancel_event=threading.Event())
    def process(*args, **kwargs):
        settings.cancel_event.set()
        return False, 'cancelled'
    with patch.object(maker, 'discover_video_files', return_value=['clip.mp4']), \
         patch.object(maker, 'process_single_video', side_effect=process):
        maker.execute_movieprint_generation(settings, LOG)
    assert settings.cancelled


def test_stopped_scrub_does_not_publish():
    handler = gui.ScrubbingHandler.__new__(gui.ScrubbingHandler)
    handler.video_path = 'clip.mp4'
    handler._scrub_queue = queue.Queue()
    handler._scrub_queue.put((1.0, 0))
    handler.app = NS(queue=queue.Queue())
    stop = threading.Event()
    extractor = MagicMock()
    extractor.__enter__.return_value = extractor
    def frame(timestamp):
        stop.set()
        return np.zeros((2, 2, 3), dtype=np.uint8)
    extractor.extract_single_frame.side_effect = frame
    with patch.object(vp, 'VideoExtractor', return_value=extractor):
        handler._scrub_worker(stop)
    assert handler.app.queue.empty()
