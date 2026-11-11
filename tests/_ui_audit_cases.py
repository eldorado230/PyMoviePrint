import shutil
import colorsys
import sys
import time
from unittest.mock import patch

import pytest

import movieprint_gui as gui
from test_studio_integration import clip


@pytest.fixture
def app(tmp_path, monkeypatch):
    if sys.platform != 'win32':
        pytest.skip('Windows GUI regression checks')
    monkeypatch.chdir(tmp_path)
    instance = gui.MoviePrintApp()
    errors = []
    instance.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr(gui.messagebox, 'askyesno', lambda *args, **kwargs: True)
    monkeypatch.setattr(gui.messagebox, 'showerror', lambda *args, **kwargs: None)
    yield instance
    assert not errors, errors
    instance._on_closing()


def wait_job(app):
    deadline = time.monotonic() + 20
    while app.is_busy and time.monotonic() < deadline:
        app.update()
        time.sleep(0.02)
    assert not app.is_busy, app.status_lbl.cget('text')


def build_preview(app, path):
    app.num_rows_var.set(1)
    app.num_columns_var.set(2)
    app._add_preview_paths([str(path)])
    wait_job(app)
    assert 'Preview ready' in app.status_lbl.cget('text')


@pytest.mark.parametrize('selection', ['picker', 'typed'])
def test_replacement_video_clears_trim_only_on_success_and_undo_restores(app, clip, tmp_path, selection):
    build_preview(app, clip)
    sheet = app.state_manager.get_state().active_sheet()
    sheet.in_point_sec, sheet.out_point_sec = 1, 1.5
    replacement = tmp_path / 'replacement.mp4'
    shutil.copyfile(clip, replacement)
    if selection == 'picker':
        build_preview(app, replacement)
    else:
        app.input_paths_var.set(str(replacement))
        app.start_thumbnail_preview_generation()
        wait_job(app)
        assert 'Preview ready' in app.status_lbl.cget('text')
    state = app.state_manager.get_state()
    assert state.active_sheet().in_point_sec is None
    assert state.active_sheet().out_point_sec is None
    assert [item['timestamp_sec'] for item in state.thumbnail_metadata] == pytest.approx([2/3, 4/3])
    app.perform_undo()
    state = app.state_manager.get_state()
    assert (state.active_sheet().in_point_sec, state.active_sheet().out_point_sec) == (1, 1.5)
    assert all(item['video_path'] == str(clip) for item in state.thumbnail_metadata)


@pytest.mark.parametrize('mode', ['Single Source', 'Batch Queue'])
def test_export_replacement_does_not_reuse_trim_but_batch_is_unchanged(app, clip, tmp_path, mode):
    build_preview(app, clip)
    sheet = app.state_manager.get_state().active_sheet()
    sheet.in_point_sec, sheet.out_point_sec = 1, 1.5
    replacement = tmp_path / 'replacement.mp4'
    shutil.copyfile(clip, replacement)
    app.input_paths_var.set(str(replacement))
    app.input_tabs.set(mode)
    app._on_tab_change()
    app.batch_file_list = [str(replacement)]
    app.output_dir_var.set(str(tmp_path / 'exports'))
    with patch.object(gui.threading, 'Thread') as worker:
        app.generate_movieprint_action()
        settings = worker.call_args.kwargs['args'][0]
    app._job_thread = None
    app._set_busy(False)
    assert (settings.start_time, settings.end_time) == (
        (None, None) if mode == 'Single Source' else (1, 1.5))
    assert (sheet.in_point_sec, sheet.out_point_sec) == (1, 1.5)


def test_same_source_keeps_trim_and_failed_replacement_preserves_sheet(app, clip, tmp_path):
    build_preview(app, clip)
    sheet = app.state_manager.get_state().active_sheet()
    sheet.in_point_sec, sheet.out_point_sec = 1, 1.5
    build_preview(app, clip)
    state = app.state_manager.get_state()
    assert [item['timestamp_sec'] for item in state.thumbnail_metadata] == pytest.approx([7/6, 4/3])
    previous = [dict(item) for item in state.thumbnail_metadata]
    app._add_preview_paths([str(tmp_path / 'missing.mp4')])
    wait_job(app)
    assert 'Preview failed' in app.status_lbl.cget('text')
    state = app.state_manager.get_state()
    assert state.thumbnail_metadata == previous
    assert (state.active_sheet().in_point_sec, state.active_sheet().out_point_sec) == (1, 1.5)


def test_theme_undo_matches_rendered_theme_and_controls(app):
    assert 'Purple' in gui.Theme.PRESET_NAMES
    assert gui.Theme.PRESETS['Purple']['ACCENT_GREEN'] == '#4E2F88'
    assert all(preset['BG_PRIMARY'] == '#181818' for preset in gui.Theme.PRESETS.values())
    assert all(preset['BG_SECONDARY'] == '#1C1B1A' for preset in gui.Theme.PRESETS.values())
    for preset in gui.Theme.PRESETS.values():
        color = preset['ACTION_GOLD'].lstrip('#')
        rgb = tuple(int(color[index:index+2], 16) / 255 for index in (0, 2, 4))
        assert colorsys.rgb_to_hsv(*rgb)[1] >= 0.4
    app.state_manager.snapshot()
    original = gui.Theme.CURRENT
    replacement = next(name for name in gui.Theme.PRESET_NAMES if name != original)
    canvas = app.preview_zoomable_canvas
    app._on_ui_theme_change(replacement)
    app.perform_undo()
    assert app.ui_theme_var.get() == gui.Theme.CURRENT == original
    assert app.preview_zoomable_canvas is canvas
    for name in gui.Theme.PRESET_NAMES:
        app._on_ui_theme_change(name)
        assert app.zoom_slider.cget('button_color') == gui.Theme.ACCENT_BLUE
        assert app.col_slider.cget('button_color') == gui.Theme.ACCENT_BLUE
        assert app.sheet_combo.cget('fg_color') == gui.Theme.BG_PRIMARY
        assert app.ui_theme_seg.cget('selected_color') == gui.Theme.ACCENT_GREEN
        app.update()
        assert app.ui_theme_seg.winfo_width() >= app.ui_theme_seg.winfo_reqwidth()


def test_toolbar_wraps_without_clipping_hidden_switch(app):
    app.geometry('1100x650')
    app.update()
    assert app.hidden_switch.grid_info()['row'] == 1
    assert app.hidden_switch.winfo_width() >= app.hidden_switch.winfo_reqwidth()
    app.library_toggle.invoke()
    app.inspector_toggle.invoke()
    app.update()
    assert app.hidden_switch.grid_info()['row'] == 0
    assert app.hidden_switch.winfo_rootx() + app.hidden_switch.winfo_width() <= (
        app.project_toolbar_row.winfo_rootx() + app.project_toolbar_row.winfo_width())
