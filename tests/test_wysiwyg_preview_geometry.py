import inspect

import movieprint_gui


def test_preview_source_frames_use_final_resolution_geometry():
    source = inspect.getsource(movieprint_gui.MoviePrintApp._thumbnail_preview_thread)
    # Reduced 480px source frames change the apparent size of pixel-based gaps,
    # margins and overlays once the final full-resolution render is scaled down.
    assert "fast_preview=True" not in source
    assert source.count("fast_preview=False") >= 2
