import logging
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import movieprint_gui as gui
import video_processing as vp
import movieprint_maker as maker
import workspace_tools
from state_manager import MoviePrintSheet, ProjectSettings
from dataclasses import asdict


@pytest.fixture
def clip(tmp_path):
    if not shutil.which(vp.FFMPEG_BIN):
        pytest.skip('FFmpeg is not installed')
    path = tmp_path / 'two-scenes.mp4'
    subprocess.run([vp.FFMPEG_BIN, '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'lavfi', '-i', 'color=c=red:s=160x90:r=25:d=1',
                    '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:r=25:d=1',
                    '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v]',
                    '-map', '[v]', '-c:v', 'mpeg4', str(path)], check=True, timeout=20)
    return path


def test_real_shot_and_interval_extraction(clip, tmp_path):
    log = logging.getLogger('real_media_test')
    ok, shots = vp.extract_shot_boundary_frames(str(clip), str(tmp_path/'shots'), log,
                                               cancel_event=threading.Event())
    assert ok and len(shots) == 2
    assert shots[0]['scene_end_sec'] == pytest.approx(1, abs=0.11)
    assert shots[1]['scene_end_sec'] == pytest.approx(2, abs=0.11)
    ok, interval = vp.extract_frames(str(clip), str(tmp_path/'interval'), log)
    assert ok and [m['timestamp_sec'] for m in interval] == [0, 1]
    ok, trimmed = vp.extract_shot_boundary_frames(str(clip), str(tmp_path/'trimmed'), log,
                                                  start_time_sec=0.5, end_time_sec=1.5)
    assert ok and len(trimmed) == 2
    assert trimmed[0]['scene_start_sec'] == 0.5
    assert trimmed[-1]['scene_end_sec'] == 1.5


def test_auto_range_keeps_nonblack_clip(clip):
    assert vp.detect_content_range(str(clip), logging.getLogger('auto_range')) == pytest.approx((0, 2))


def test_real_shot_grid_cli(clip, tmp_path):
    output = tmp_path / 'output'
    completed = subprocess.run([sys.executable, str(Path(gui.__file__).with_name('movieprint_maker.py')),
                                str(clip), str(output), '--extraction_mode', 'shot', '--rows', '1', '--columns', '2'],
                               capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert len(list(output.glob('*.jpg'))) == 1


def test_sheet_snapshot_export_with_individual_frames(clip, tmp_path):
    defaults = ProjectSettings(num_rows=1, num_columns=2, include_individual_frames=True)
    sheet = MoviePrintSheet(name='My edits', settings=asdict(defaults), thumbnail_metadata=[
        dict(video_path=str(clip), timestamp_sec=0.25, id='a'),
        dict(video_path=str(clip), timestamp_sec=1.25, id='b')])
    settings = workspace_tools.sheet_export_settings(sheet, str(tmp_path/'exports'), 1)
    good, bad = maker.execute_movieprint_generation(settings, logging.getLogger('sheet_export_test'))
    assert len(good) == 1 and not bad
    assert (tmp_path/'exports'/'001_My edits.jpg').is_file()
    assert len(list((tmp_path/'exports'/'001_My edits_frames').glob('*.jpg'))) == 2
    assert sheet.settings['output_filename'] == ''


@pytest.mark.parametrize('mode', ['grid', 'timeline'])
@pytest.mark.parametrize('extension', ['jpg', 'png', 'webp'])
def test_real_export_format_and_layout_matrix(clip, tmp_path, mode, extension):
    settings = ProjectSettings(num_rows=1, num_columns=2, layout_mode=mode,
        frame_format=extension, fit_to_output_params=True, output_width=640, output_height=360,
        crop_left=5, rotate_thumbnails=90, show_header=True, show_header_timeline=True,
        frame_info_show=True, rounded_corners=12)
    sheet = MoviePrintSheet(settings=asdict(settings), thumbnail_metadata=[
        dict(video_path=str(clip), timestamp_sec=0.25, scene_start_sec=0, scene_end_sec=1),
        dict(video_path=str(clip), timestamp_sec=1.25, scene_start_sec=1, scene_end_sec=2)])
    job = workspace_tools.sheet_export_settings(sheet, str(tmp_path / 'matrix'), 1)
    good, bad = maker.execute_movieprint_generation(job, logging.getLogger('matrix'))
    assert len(good) == 1 and not bad
    from PIL import Image
    with Image.open(good[0]['output']) as image:
        assert image.size == (640, 360)
        image.verify()


@pytest.mark.parametrize('transfer,kind', [('smpte2084', 'PQ'), ('arib-std-b67', 'HLG')])
def test_real_hdr_detection_and_tonemapping(tmp_path, transfer, kind):
    path = tmp_path / f'{kind}.mp4'
    subprocess.run([vp.FFMPEG_BIN, '-hide_banner', '-loglevel', 'error', '-y',
        '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=25:duration=1',
        '-c:v', 'libx265', '-pix_fmt', 'yuv420p10le', '-color_primaries', 'bt2020',
        '-color_trc', transfer, '-colorspace', 'bt2020nc', '-x265-params',
        f'colorprim=9:transfer={16 if kind == "PQ" else 18}:colormatrix=9', str(path)],
        check=True, capture_output=True, timeout=30)
    probe = subprocess.run([vp.FFPROBE_BIN, '-v', 'error', '-show_streams', '-of', 'json', str(path)],
                           capture_output=True, text=True, check=True, timeout=10)
    assert transfer in probe.stdout, probe.stdout
    with vp.VideoExtractor(str(path), logging.getLogger('hdr')) as extractor:
        assert extractor.detect_hdr_type() == kind
    ok, frames = vp.extract_frames_from_timestamps(str(path), [0.25],
        str(tmp_path / 'frames'), logging.getLogger('hdr'), hdr_tonemap=True)
    assert ok and len(frames) == 1
    from PIL import Image
    with Image.open(frames[0]['frame_path']) as image:
        assert image.size == (160, 90)


@pytest.mark.parametrize('cancel', [False, True])
@pytest.mark.parametrize('wrapper', [False, pytest.param(True, marks=pytest.mark.skipif(
    sys.platform != 'win32', reason='Windows package-manager shim check'))])
def test_real_ffmpeg_timeout_and_cancellation(cancel, wrapper):
    import time
    event = threading.Event()
    timer = threading.Timer(0.2, event.set) if cancel else None
    if timer:
        timer.start()
    start = time.monotonic()
    try:
        cmd = [vp.FFMPEG_BIN, '-hide_banner', '-loglevel', 'error', '-re', '-f', 'lavfi',
               '-i', 'color=red:size=16x16:rate=1', '-t', '30', '-f', 'null', '-']
        if wrapper:
            cmd = [sys.executable, '-c', 'import subprocess, sys; subprocess.run(sys.argv[1:])'] + cmd
        ok = vp.VideoUtils.run_ffmpeg_command_with_control(
            cmd,
            logging.getLogger('cancel'), cancel_event=event, timeout=5 if cancel else 0.3)
        assert not ok
        assert time.monotonic() - start < 7
    finally:
        if timer:
            timer.cancel()


@pytest.mark.skipif(sys.platform != 'win32', reason='Local Windows GUI lifecycle check')
def test_gui_initialization_and_sheet_controls(tmp_path, monkeypatch, clip):
    monkeypatch.chdir(tmp_path)
    app = gui.MoviePrintApp()
    try:
        app.after(350, app.quit)
        app.mainloop()
        assert app.save_btn.winfo_rooty()+app.save_btn.winfo_height() <= app.winfo_rooty()+app.winfo_height()
        app.add_sheet()
        assert len(app.state_manager.get_state().sheets) == 2
        app.duplicate_sheet()
        app.delete_sheet()
        app.output_dir_var.set(str(tmp_path))
        app.include_individual_frames_var.set(True)
        app._toggle_frame_export_options()
        assert app.frames_dir_frame.winfo_manager() == 'pack'
        app._set_busy(True)
        assert app.input_entry.cget('state') == 'disabled'
        assert app.sort_combo.cget('state') == 'disabled'
        app._set_busy(False)
        assert app.input_entry.cget('state') == 'normal'
        assert app.sort_combo.cget('state') == 'normal'
        _check_studio_layout_inspector_modes_and_theme(app)
        from studio_e2e_checks import check_real_workflows
        check_real_workflows(app, clip, tmp_path, monkeypatch)
    finally:
        app._on_closing()


def _check_studio_layout_inspector_modes_and_theme(app):
    original_theme = gui.Theme.CURRENT
    try:
        assert app.sidebar_frame._parent_frame.grid_info()['column'] == 0
        assert app.inspector_frame._parent_frame.grid_info()['column'] == 2
        assert app.topbar_frame.grid_info()['row'] == 0
        assert app.action_frame.grid_info()['row'] == 3
        assert app.preview_btn.master is app.topbar_actions
        assert app.save_btn.master is app.topbar_actions
        assert app.input_tabs.master is app.sidebar_frame
        assert app.slider_frame.master is app.inspector_frame
        assert app.save_next_to_video_cb.cget('text') == 'Save next to each video file'
        assert app.save_next_to_video_var.get() == (not app.output_dir_var.get().strip())

        app.input_tabs.set('Batch Queue')
        app._on_tab_change()
        assert app.preview_btn.cget('state') == 'disabled'
        app.input_tabs.set('Single Source')
        app._on_tab_change()
        assert app.preview_btn.cget('state') == 'normal'
        for mode in ('timeline', 'grid'):
            app.layout_mode_var.set(mode)
            app._on_layout_mode_change(mode)
            assert app.slider_frame.winfo_manager() == ('pack' if mode == 'grid' else '')

        app.state_manager.get_state().thumbnail_metadata = [
            dict(id='frame-a', video_path='Video A.mp4', timestamp_sec=1.25)]
        app.selected_thumbnail_index = 0
        app._refresh_selected_inspector()
        assert app.selection_title.cget('text') == 'Frame 1'
        assert 'Video A.mp4' in app.selection_detail.cget('text')
        assert '1.250 seconds' in app.selection_detail.cget('text')
        assert app.selection_actions.winfo_manager() == 'pack'
        app.selected_thumbnail_index = None
        app._refresh_selected_inspector()
        assert app.selection_actions.winfo_manager() == ''
        app.state_manager.get_state().thumbnail_metadata = []

        new_theme = next(t for t in gui.Theme.PRESET_NAMES if t != original_theme)
        app._add_batch_paths(['C:/audit-a.mp4', 'C:/audit-b.mp4'])
        app.batch_listbox.selection_set(1)
        app.input_tabs.set('Batch Queue')
        app._on_tab_change()
        errors = []
        app.report_callback_exception = lambda *args: errors.append(args)
        trace_count = len(app.output_filename_var.trace_info())
        app.update_idletasks()
        original_width = app.main_area.winfo_width()
        app.library_toggle.invoke()
        app.inspector_toggle.invoke()
        app.update_idletasks()
        assert not app.sidebar_frame._parent_frame.winfo_ismapped()
        assert not app.inspector_frame._parent_frame.winfo_ismapped()
        assert app.library_toggle.winfo_ismapped() and app.inspector_toggle.winfo_ismapped()
        assert app.main_area.winfo_width() > original_width
        assert app.library_toggle.cget('text') == '›'
        assert app.inspector_toggle.cget('text') == '‹'
        app._apply_ui_theme(new_theme)
        app._apply_ui_theme(original_theme)
        app.update_idletasks()
        assert not app.library_visible and not app.inspector_visible
        assert app.library_toggle.winfo_ismapped() and app.inspector_toggle.winfo_ismapped()
        app.library_toggle.invoke()
        app.inspector_toggle.invoke()
        app.update_idletasks()
        assert app.sidebar_frame._parent_frame.winfo_ismapped()
        assert app.inspector_frame._parent_frame.winfo_ismapped()
        assert app.brand_label.cget('text') == 'PyMoviePrint'
        assert app.preview_btn.cget('font').cget('family') == gui.Theme.FONT_FAMILY
        assert app.brand_label.cget('font')[0] == gui.Theme.FONT_FAMILY
        assert app.input_tabs.get() == 'Batch Queue'
        assert list(app.batch_listbox.get(0, 'end')) == app.batch_file_list
        assert app.batch_listbox.curselection() == (1,)
        assert app.preview_btn.cget('state') == 'disabled'
        assert app.editing_hint.winfo_ismapped()
        assert 'Right-click' in app.editing_hint.cget('text')
        app.geometry('1100x650')
        app.update_idletasks()
        def find_buttons(widget):
            for child in widget.winfo_children():
                if isinstance(child, gui.ctk.CTkButton):
                    yield child
                yield from find_buttons(child)
        controls = [b for b in find_buttons(app.input_tabs.tab('Batch Queue'))
                    if b.cget('text') in ('Add Files', 'Add Folder', 'Clear', 'Remove Selected')]
        assert len(controls) == 4
        for button in controls:
            assert button.winfo_height() >= round(27 * button._get_widget_scaling())
        assert isinstance(app.sidebar_frame, gui.ctk.CTkScrollableFrame)
        # The bottom controls are reachable by scrolling, not truncated inside the tab.
        app.sidebar_frame._parent_canvas.yview_moveto(1)
        app.update_idletasks()
        for button in controls:
            assert button.winfo_rooty() + button.winfo_height() <= (
                app.sidebar_frame._parent_canvas.winfo_rooty() + app.sidebar_frame._parent_canvas.winfo_height())
        app.clear_batch_list()
        app.input_tabs.set('Single Source')
        app._on_tab_change()
        import traceback
        assert not errors, '\n'.join(''.join(traceback.format_exception(*e)) for e in errors)
        assert len(app.output_filename_var.trace_info()) == trace_count
        assert app.output_path_preview.cget('text')
        assert app.save_next_to_video_var.get() == (not app.output_dir_var.get().strip())
        assert app.preview_btn.master is app.topbar_actions
        assert app.slider_frame.master is app.inspector_frame
        assert app.input_tabs.master is app.sidebar_frame
        app._set_busy(True)
        assert app.preview_btn.cget('state') == 'disabled'
        assert app.col_slider.cget('state') == 'disabled'
        app._set_busy(False)
        assert app.preview_btn.cget('state') == 'normal'
    finally:
        gui.Theme.apply_preset(original_theme)
