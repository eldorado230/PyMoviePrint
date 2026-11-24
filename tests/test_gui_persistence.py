import json
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import movieprint_gui as gui


def test_legacy_source_field_accepts_literal_files_and_separated_sources(tmp_path):
    literal = tmp_path / 'a; b.mp4'
    literal.touch()
    app = SimpleNamespace(_internal_input_paths=[])
    app.input_paths_var = SimpleNamespace(get=lambda: str(literal))
    assert gui.MoviePrintApp._current_source_paths(app) == [str(literal)]
    app.input_paths_var.get = lambda: ' one.mp4 ; ; two.mkv '
    assert gui.MoviePrintApp._current_source_paths(app) == ['one.mp4', 'two.mkv']


@pytest.mark.parametrize('structured', [False, True])
def test_saved_source_paths_restore_to_entry_and_state(tmp_path, monkeypatch, structured):
    # A structured selection remains exact even when the source is offline.
    paths = ['offline; source.mp4', 'other; source.mkv'] if structured else ['one.mp4', 'two.mkv']
    destination = tmp_path / 'settings.json'
    settings = {'input_paths': '; '.join(paths), 'num_rows': 3}
    if structured:
        settings['input_paths_list'] = paths
    destination.write_text(json.dumps(settings), encoding='utf-8')
    monkeypatch.setattr(gui, 'SETTINGS_FILE', str(destination))

    class Entry:
        value = ''

        def get(self):
            return self.value

        def set(self, value):
            self.value = value
            gui.MoviePrintApp._on_setting_change(app, 'input_paths_var', 'input_paths')

    app = SimpleNamespace(
        _internal_input_paths=[], input_paths_var=Entry(), state_manager=Mock(),
        settings_map={'input_paths_var': 'input_paths', 'num_rows_var': 'num_rows'},
        col_slider=Mock(), row_slider=Mock(), num_columns_var=Mock(get=lambda: 5),
        num_rows_var=Mock(get=lambda: 3), update_visibility_state=Mock(),
        _toggle_naming_inputs=Mock(), _toggle_hdr_options=Mock(),
        scrubbing_handler=SimpleNamespace(_worker_thread=None), player_window=None,
        preview_temp_dir=None, _cleanup_garbage_dirs=Mock(), destroy=Mock(),
    )
    app._current_source_paths = lambda: gui.MoviePrintApp._current_source_paths(app)
    app._set_single_source_paths = lambda selected: gui.MoviePrintApp._set_single_source_paths(app, selected)
    gui.MoviePrintApp._load_persistent_settings(app)
    app.state_manager.update_settings.assert_called_once_with({'input_paths': paths}, commit=False)
    app.num_rows_var.set.assert_called_once_with(3)
    gui.MoviePrintApp._finish_closing_when_idle(app)
    saved = json.loads(destination.read_bytes())
    assert saved['input_paths_list'] == paths
    assert saved['input_paths'] == '; '.join(paths)


@pytest.mark.parametrize('failure', ['serialization', 'flush', 'replace'])
def test_failed_settings_save_preserves_previous_snapshot(tmp_path, monkeypatch, failure):
    destination = tmp_path / 'settings.json'
    gui._write_gui_settings(destination, {'rows': 3})
    original = destination.read_bytes()

    def fail(*args):
        raise OSError('injected disk error')

    payload = {'rows': 8}
    if failure == 'serialization':
        payload['invalid'] = object()
    elif failure == 'flush':
        monkeypatch.setattr(os, 'fsync', fail)
    else:
        monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(TypeError if failure == 'serialization' else OSError):
        gui._write_gui_settings(destination, payload)
    assert destination.read_bytes() == original
    assert list(tmp_path.iterdir()) == [destination]


def write_settings_snapshots(destination, editor):
    for sequence in range(12):
        gui._write_gui_settings(destination, {'editor': editor, 'sequence': sequence, 'payload': str(editor) * 4096})


def test_multiple_editors_publish_only_complete_settings(tmp_path):
    destination = tmp_path / 'settings.json'
    gui._write_gui_settings(destination, {'editor': 0, 'sequence': 0, 'payload': '0' * 4096})
    with ProcessPoolExecutor(max_workers=3, mp_context=get_context('spawn')) as executor:
        jobs = [executor.submit(write_settings_snapshots, destination, editor) for editor in (1, 2, 3)]
        while not all(job.done() for job in jobs):
            try:
                observed = json.loads(destination.read_bytes())
            except PermissionError:
                # Windows may deny a new handle during a rename.
                time.sleep(0.01)
                continue
            assert observed['payload'] == str(observed['editor']) * 4096
            time.sleep(0.01)
        for job in jobs:
            job.result()
    final = json.loads(destination.read_bytes())
    assert final['editor'] in (1, 2, 3) and final['sequence'] == 11
    assert list(tmp_path.iterdir()) == [destination]


def test_windowed_logging_writes_startup_diagnostics_without_standard_streams(tmp_path, monkeypatch):
    logger = logging.getLogger()
    existing_handlers = list(logger.handlers)
    original_level = logger.level
    monkeypatch.setattr(gui.os.path, 'expanduser', lambda _: str(tmp_path))
    monkeypatch.setattr(gui.DependencyManager, 'LOAD_FAILURES', [('example', 'test fault', 'trace detail')])
    try:
        with monkeypatch.context() as patch:
            patch.setattr(sys, 'stdout', None)
            patch.setattr(sys, 'stderr', None)
            patch.setattr(sys, 'excepthook', sys.excepthook)
            gui.setup_file_logging()
            added = [handler for handler in logger.handlers if handler not in existing_handlers]
            assert len(added) == 1
            assert isinstance(added[0], logging.handlers.RotatingFileHandler)
            logger.info('windowed startup check')
        saved = (tmp_path / 'pymovieprint.log').read_text(encoding='utf-8')
        assert 'windowed startup check' in saved and 'trace detail' in saved
    finally:
        for handler in list(logger.handlers):
            if handler not in existing_handlers:
                logger.removeHandler(handler)
                handler.close()
        logger.setLevel(original_level)
