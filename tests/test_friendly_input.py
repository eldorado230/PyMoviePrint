from types import SimpleNamespace as NS
from unittest.mock import Mock

import movieprint_gui as gui


def app_with_frames(frames=()):
    return NS(is_busy=False, state_manager=NS(get_state=lambda: NS(thumbnail_metadata=frames)),
              input_tabs=Mock(), _on_tab_change=Mock(), _set_single_source_paths=Mock(),
              start_thumbnail_preview_generation=Mock())


def test_add_video_previews_and_selects_single_source():
    app = app_with_frames()
    gui.MoviePrintApp._add_preview_paths(app, ['movie.mp4'])
    app.input_tabs.set.assert_called_once_with('Single Source')
    app._set_single_source_paths.assert_called_once_with(['movie.mp4'])
    app.start_thumbnail_preview_generation.assert_called_once()


def test_replace_preview_declined_preserves_inputs(monkeypatch):
    app = app_with_frames([{'timestamp_sec': 1}])
    monkeypatch.setattr(gui.messagebox, 'askyesno', lambda *a, **k: False)
    gui.MoviePrintApp._add_preview_paths(app, ['new.mp4'])
    app._set_single_source_paths.assert_not_called()
    app.start_thumbnail_preview_generation.assert_not_called()


def test_multi_selection_explains_first_video_preview(monkeypatch):
    app = app_with_frames()
    info = Mock()
    monkeypatch.setattr(gui.messagebox, 'showinfo', info)
    gui.MoviePrintApp._add_preview_paths(app, ['a.mp4', 'b.mp4'])
    assert 'first video' in info.call_args.args[1]
    app._set_single_source_paths.assert_called_once_with(['a.mp4', 'b.mp4'])
    app.start_thumbnail_preview_generation.assert_called_once()


def test_busy_drop_does_not_change_inputs():
    gui.MoviePrintApp.handle_drop(NS(is_busy=True), NS(data='anything'))


def test_batch_drop_only_enqueues():
    app = NS(is_busy=False, tk=NS(splitlist=lambda value: ('a.mp4', 'b.mp4')),
             input_tabs=NS(get=lambda: 'Batch Queue'), _add_batch_paths=Mock(), _add_preview_paths=Mock())
    gui.MoviePrintApp.handle_drop(app, NS(data='ignored'))
    app._add_batch_paths.assert_called_once_with(('a.mp4', 'b.mp4'))
    app._add_preview_paths.assert_not_called()


def test_single_drop_starts_preview():
    app = NS(is_busy=False, tk=NS(splitlist=lambda value: ('a.mp4',)),
             input_tabs=NS(get=lambda: 'Single Source'), _add_preview_paths=Mock())
    gui.MoviePrintApp.handle_drop(app, NS(data='ignored'))
    app._add_preview_paths.assert_called_once_with(('a.mp4',))


def test_picker_cancel_does_nothing(monkeypatch):
    monkeypatch.setattr(gui.filedialog, 'askopenfilenames', lambda **kw: ())
    app = NS(is_busy=False, _add_preview_paths=Mock())
    gui.MoviePrintApp.browse_input_paths(app)
    app._add_preview_paths.assert_not_called()
