"""Real GUI controllers, worker threads and FFmpeg; dialogs alone are automated."""
import shutil
import time
from types import SimpleNamespace
from pathlib import Path

from PIL import Image
import pytest
import movieprint_gui as gui
import project_io


def check_real_workflows(app, clip, tmp_path, monkeypatch):
    messages, errors = [], []
    for method in ('showinfo', 'showwarning', 'showerror'):
        monkeypatch.setattr(gui.messagebox, method,
                            lambda title, text, m=method, **kw: messages.append((m, title, text)))
    monkeypatch.setattr(gui.messagebox, 'askyesno', lambda *a, **k: True)
    monkeypatch.setattr(app, 'report_callback_exception', lambda *a: errors.append(a))

    def wait_job():
        deadline = time.monotonic() + 40
        while app.is_busy and time.monotonic() < deadline:
            app.update()
            time.sleep(0.02)
        assert not app.is_busy, app.status_lbl.cget('text')
        assert not errors, errors
        assert not [m for m in messages if m[0] == 'showerror'], messages

    app._set_single_source_paths([str(clip)])
    app.num_rows_var.set(1)
    app.num_columns_var.set(2)
    app.extraction_mode_var.set('shot')
    app.layout_mode_var.set('grid')
    app.include_individual_frames_var.set(False)
    app.output_frames_only_var.set(False)
    monkeypatch.setattr(gui.filedialog, 'askopenfilenames', lambda **k: (str(clip),))
    app.browse_input_paths()
    assert app.is_busy
    wait_job()
    state = app.state_manager.get_state()
    assert len(state.thumbnail_metadata) == 2
    assert app.preview_zoomable_canvas.original_image is not None
    assert not app.is_landing_state
    assert app.editing_hint.winfo_ismapped()
    assert app.library_toggle.winfo_ismapped() and app.inspector_toggle.winfo_ismapped()
    assert app.selected_thumbnail_index is None
    assert any('2 frames' in app.source_library.item(child, 'text')
               for parent in app.source_library.get_children()
               for child in app.source_library.get_children(parent))

    # Frame edit, hide/show, undo/redo and scene tools operate on real frames.
    app.selected_thumbnail_index = 0
    app.replace_selected_thumbnail(0.25)
    assert state.thumbnail_metadata[0]['timestamp_sec'] == 0.25
    app.step_selected_frame(1)
    assert state.thumbnail_metadata[0]['timestamp_sec'] == pytest.approx(0.29)
    app.toggle_selected_hidden()
    assert state.thumbnail_metadata[0]['hidden']
    app.perform_undo()
    assert not app.state_manager.get_state().thumbnail_metadata[0]['hidden']
    app.perform_redo()
    app.toggle_selected_hidden()
    monkeypatch.setattr(gui.simpledialog, 'askfloat', lambda *a, **k: 0.5)
    app.cut_scene_action()
    assert len(app.state_manager.get_state().thumbnail_metadata) == 3
    app.merge_scene_action()
    assert len(app.state_manager.get_state().thumbnail_metadata) == 2
    app.explore_scene_action()
    assert len(app.state_manager.get_state().thumbnail_metadata) == 12
    assert app.state_manager.get_state().active_sheet().parent_sheet_id
    app.delete_sheet()

    # Styling, timeline, selected-frame saving, EDL and player seek.
    app.selected_thumbnail_index = 0
    app.show_header_var.set(True)
    app.show_header_timeline_var.set(True)
    app.frame_info_show_var.set(True)
    app.crop_left_var.set(5)
    app.rotate_thumbnails_var.set(90)
    app.layout_mode_var.set('timeline')
    app.quick_refresh_layout()
    assert app.state_manager.get_state().thumbnail_layout_data
    app.layout_mode_var.set('grid')
    app.rotate_thumbnails_var.set(0)
    app.crop_left_var.set(0)
    app.quick_refresh_layout()
    frame = tmp_path / 'selected.jpg'
    monkeypatch.setattr(gui.filedialog, 'asksaveasfilename', lambda **k: str(frame))
    app.save_selected_frame()
    with Image.open(frame) as im:
        im.verify()
    png_frame = tmp_path / 'selected.png'
    monkeypatch.setattr(gui.filedialog, 'asksaveasfilename', lambda **k: str(png_frame))
    app.save_selected_frame()
    with Image.open(png_frame) as im:
        assert im.format == 'PNG'
    edl = tmp_path / 'cuts.edl'
    monkeypatch.setattr(gui.filedialog, 'asksaveasfilename', lambda **k: str(edl))
    app.export_edl_action()
    assert 'FROM CLIP NAME' in edl.read_text()
    app.open_player()
    assert app.player_window is not None
    app.player_window.seek_to(1.25)
    assert app.player_window.current_timestamp == pytest.approx(1.25)
    # Theme changes must recolour the live workspace, not reconstruct it.
    import copy
    canvas = app.preview_zoomable_canvas
    canvas.set_zoom(1.5)
    app.zoom_level_var.set(1.5)
    app.update_idletasks()
    canvas.canvas.xview_moveto(0.1)
    pixels = canvas.original_image
    player = app.player_window
    source_state = app.state_manager.get_state()
    metadata_before = copy.deepcopy(source_state.thumbnail_metadata)
    selected_before = app.selected_thumbnail_index
    status_before = app.status_lbl.cget('text')
    scroll_before = canvas.canvas.xview()
    for theme in gui.Theme.PRESET_NAMES:
        app._apply_ui_theme(theme)
        app.update_idletasks()
        assert app.preview_zoomable_canvas is canvas
        assert canvas.original_image is pixels
        assert canvas.winfo_ismapped()
        assert not app.is_landing_state
        assert canvas._zoom_level == 1.5 and not canvas._auto_fit
        assert canvas.canvas.xview() == scroll_before
        assert app.player_window is player and player.winfo_exists()
        assert player.current_timestamp == pytest.approx(1.25)
        assert app.state_manager.get_state() is source_state
        assert source_state.thumbnail_metadata == metadata_before
        assert app.selected_thumbnail_index == selected_before
        assert app.status_lbl.cget('text') == status_before
        assert app.cget('fg_color') == gui.Theme.BG_PRIMARY
    assert not errors
    canvas.fit_to_window()
    app.update_idletasks()
    assert canvas._auto_fit
    assert canvas._zoom_level == pytest.approx(canvas._calculate_fit_zoom(
        pixels.width, pixels.height, canvas.canvas.winfo_width(), canvas.canvas.winfo_height()))
    monkeypatch.setenv('SDL_AUDIODRIVER', 'dummy')
    app.player_window.play_with_audio()
    playback = app.player_window._audio_process
    audio_log = app.player_window._audio_errors
    app.player_window.close()
    playback.wait(timeout=5)
    assert audio_log.closed

    # Fast drag/release must finish at the latest requested timestamp.
    app.scrubbing_handler.start(SimpleNamespace(x=0), 0, 0.25, str(clip))
    for x in (5, 15, 25, 50):
        app.scrubbing_handler.handle_motion(SimpleNamespace(x=x))
    app.scrubbing_handler.stop(None)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.update()
        if app.state_manager.get_state().thumbnail_metadata[0]['timestamp_sec'] == 1.25:
            break
        time.sleep(0.02)
    assert app.state_manager.get_state().thumbnail_metadata[0]['timestamp_sec'] == 1.25
    app.replace_selected_thumbnail(0.25)

    app.auto_range_action()
    wait_job()
    assert app.state_manager.get_state().active_sheet().out_point_sec == pytest.approx(2)
    model_dir = gui.DependencyManager.face_analysis.model_directory()
    if all((model_dir / spec[0]).is_file() for spec in gui.DependencyManager.face_analysis.MODEL_SPECS):
        app.analyze_faces_action()
        wait_job()
        assert all('face_detection' in i for i in app.state_manager.get_state().thumbnail_metadata)

    # Save/open with frame files removed forces source recovery.
    project = tmp_path / 'session.pymovieprint.json'
    app.current_project_path = str(project)
    app.save_project_action()
    saved, _ = project_io.load_project(str(project))
    assert len(saved.thumbnail_metadata) == 2
    for sheet in saved.sheets:
        for item in sheet.thumbnail_metadata:
            Path(item['frame_path']).unlink(missing_ok=True)
    monkeypatch.setattr(gui.filedialog, 'askopenfilename', lambda **k: str(project))
    app.open_project_action()
    assert all(Path(i['frame_path']).is_file() for i in app.state_manager.get_state().thumbnail_metadata)

    # Real single export + individual frames + embedded editable PNG.
    output = tmp_path / 'exports'
    app.output_dir_var.set(str(output))
    app.output_naming_mode_var.set('custom')
    app.output_filename_var.set('Verified.png')
    app.frame_format_var.set('png')
    app.include_individual_frames_var.set(True)
    assert not app.save_next_to_video_var.get()
    app.save_next_to_video_cb.toggle()
    assert app.save_next_to_video_var.get()
    assert app.output_dir_var.get() == ''
    app.generate_movieprint_action()
    wait_job()
    assert (clip.parent / 'Verified.png').is_file()
    assert not (output / 'Verified.png').exists()
    # Cancelling folder selection must not misrepresent the active destination.
    monkeypatch.setattr(gui.filedialog, 'askdirectory', lambda **k: '')
    app.save_next_to_video_cb.toggle()
    assert app.save_next_to_video_var.get()
    monkeypatch.setattr(gui.filedialog, 'askdirectory', lambda **k: str(output))
    app.save_next_to_video_cb.toggle()
    assert not app.save_next_to_video_var.get()
    assert app.output_dir_var.get() == str(output)
    app.generate_movieprint_action()
    wait_job()
    assert (output / 'Verified.png').is_file()
    assert len(list((output / 'Verified_frames').glob('*.png'))) == 2
    embedded, _ = project_io.load_project(str(output / 'Verified.png'))
    assert len(embedded.thumbnail_metadata) == 2
    # Export every populated sheet; this fixture also contains an empty sheet.
    app.state_manager.get_state().sheets = [app.state_manager.get_state().active_sheet()]
    app.duplicate_sheet()
    all_output = tmp_path / 'all-sheets'
    monkeypatch.setattr(gui.filedialog, 'askdirectory', lambda **k: str(all_output))
    app.export_all_sheets_action()
    wait_job()
    assert len(list(all_output.glob('*.png'))) == 2
    app.overwrite_mode_var.set('skip')
    app.generate_movieprint_action()
    wait_job()
    assert 'skipped' in app.status_lbl.cget('text')

    # A movie library commonly stores one video and fanart.jpg per folder.
    library = tmp_path / 'library'
    first_folder, second_folder = library / 'Movie One', library / 'Movie Two'
    first_folder.mkdir(parents=True)
    second_folder.mkdir()
    shutil.copy2(clip, first_folder / 'movie.mp4')
    shutil.copy2(clip, second_folder / 'movie.mp4')
    existing = first_folder / 'fanart.jpg'
    existing.write_bytes(b'existing fanart')
    app.input_tabs.set('Batch Queue')
    app._on_tab_change()
    app.clear_batch_list()
    app._add_batch_paths([str(library)])
    app.recursive_scan_var.set(True)
    app.output_dir_var.set('')
    app.output_filename_var.set('fanart')
    app.frame_format_var.set('jpg')
    app.include_individual_frames_var.set(False)
    app.overwrite_mode_var.set('skip')
    app.generate_movieprint_action()
    wait_job()
    assert existing.read_bytes() == b'existing fanart'
    assert (second_folder / 'fanart.jpg').is_file()
    assert '1 created, 1 skipped' in app.status_lbl.cget('text')
    app.overwrite_mode_var.set('overwrite')
    app.generate_movieprint_action()
    wait_job()
    with Image.open(existing) as image:
        image.verify()
    assert '2 movieprint(s) created' in app.status_lbl.cget('text')
    second_video = first_folder / 'extra.mp4'
    shutil.copy2(clip, second_video)
    original_fanart = existing.read_bytes()
    other_fanart = second_folder / 'fanart.jpg'
    other_fanart.write_bytes(b'replace this output')
    app.generate_movieprint_action()
    wait_job()
    assert existing.read_bytes() == original_fanart
    with Image.open(other_fanart) as image:
        image.verify()
    assert '1 succeeded, 2 failed' in app.status_lbl.cget('text')
    second_video.unlink()
    shared = tmp_path / 'shared-output'
    shared.mkdir()
    shared_fanart = shared / 'fanart.jpg'
    shared_fanart.write_bytes(b'keep this output')
    app.output_dir_var.set(str(shared))
    app.overwrite_mode_var.set('skip')
    app.generate_movieprint_action()
    wait_job()
    assert '0 created, 2 skipped' in app.status_lbl.cget('text')
    assert shared_fanart.read_bytes() == b'keep this output'
    app.overwrite_mode_var.set('overwrite')
    app.generate_movieprint_action()
    assert not app.is_busy
    assert messages[-1][0] == 'showerror'
    assert '{movie}' in messages[-1][2]
    assert shared_fanart.read_bytes() == b'keep this output'
    messages.clear()
    app.clear_batch_list()
    app.recursive_scan_var.set(False)
    app.output_dir_var.set(str(output))
    app.frame_format_var.set('png')
    app.output_filename_var.set('Verified.png')
    app.input_tabs.set('Single Source')
    app._on_tab_change()

    # Multi-file collision check, safe batch, mixed failure, empty input.
    second = tmp_path / 'second.mp4'
    shutil.copy2(clip, second)
    app._set_single_source_paths([str(clip), str(second)])
    app.generate_movieprint_action()
    assert not app.is_busy
    assert messages[-1][0] == 'showerror'
    messages.clear()
    app.include_individual_frames_var.set(False)
    app.output_naming_mode_var.set('suffix')
    app.output_filename_suffix_var.set('_test')
    app.input_tabs.set('Batch Queue')
    app._on_tab_change()
    app._add_batch_paths([str(clip), str(second)])
    app.generate_movieprint_action()
    wait_job()
    assert (output / 'two-scenes_test.png').is_file()
    assert (output / 'second_test.png').is_file()
    broken = tmp_path / 'broken.mp4'
    broken.write_bytes(b'not a movie')
    app.clear_batch_list()
    app._add_batch_paths([str(clip), str(broken)])
    app.overwrite_mode_var.set('overwrite')
    app.generate_movieprint_action()
    wait_job()
    assert '1 succeeded, 1 failed' in app.status_lbl.cget('text')
    app.input_tabs.set('Single Source')
    app._on_tab_change()
    empty = tmp_path / 'empty'
    empty.mkdir()
    app._set_single_source_paths([str(empty)])
    app.generate_movieprint_action()
    wait_job()
    assert 'Nothing was generated' in app.status_lbl.cget('text')
    previous = list(app.state_manager.get_state().thumbnail_metadata)
    app._set_single_source_paths([str(broken)])
    app.start_thumbnail_preview_generation()
    deadline = time.monotonic() + 10
    while app.is_busy and time.monotonic() < deadline:
        app.update()
        time.sleep(0.02)
    assert not app.is_busy
    assert sum(m[0] == 'showerror' for m in messages) == 1
    assert 'Preview failed' in messages[-1][2]
    assert app.state_manager.get_state().thumbnail_metadata == previous
    messages.clear()
    app._set_single_source_paths([str(clip)])
    app.start_thumbnail_preview_generation()
    app.cancel_active_job()
    wait_job()
    assert 'cancelled' in app.status_lbl.cget('text').lower()
    assert app.state_manager.get_state().thumbnail_metadata == previous
    assert not errors
