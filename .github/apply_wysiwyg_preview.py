from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path, old, new, label):
    file_path = ROOT / path
    text = file_path.read_text(encoding='utf-8')
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match in {path}, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding='utf-8')


# A WYSIWYG preview must enter the layout renderer with the same source-frame
# dimensions as final generation. The old 480px fast-preview frames made fixed
# pixel gaps/margins occupy a different visual proportion than the final image.
replace_once(
    'movieprint_gui.py',
    '''                    success, meta = DependencyManager.video_processing.extract_frames(\n                        video_path, temp_dir, logger, \n                        interval_seconds=interval, \n                        fast_preview=True, \n                        hdr_tonemap=True, \n                        hdr_algorithm=config['hdr_algorithm']\n                    )\n''',
    '''                    success, meta = DependencyManager.video_processing.extract_frames(\n                        video_path, temp_dir, logger,\n                        interval_seconds=interval,\n                        fast_preview=False,\n                        hdr_tonemap=True,\n                        hdr_algorithm=config['hdr_algorithm']\n                    )\n''',
    'use full-resolution HDR preview frames',
)

replace_once(
    'movieprint_gui.py',
    '''                    success, meta = DependencyManager.video_processing.extract_frames_from_timestamps(\n                        video_path, timestamps, temp_dir, logger, fast_preview=True\n                    )\n''',
    '''                    success, meta = DependencyManager.video_processing.extract_frames_from_timestamps(\n                        video_path, timestamps, temp_dir, logger, fast_preview=False\n                    )\n''',
    'use full-resolution timestamp preview frames',
)

(ROOT / 'tests' / 'test_wysiwyg_preview_geometry.py').write_text('''import inspect\n\nimport movieprint_gui\n\n\ndef test_preview_source_frames_use_final_resolution_geometry():\n    source = inspect.getsource(movieprint_gui.MoviePrintApp._thumbnail_preview_thread)\n    # Reduced 480px source frames change the apparent size of pixel-based gaps,\n    # margins and overlays once the final full-resolution render is scaled down.\n    assert "fast_preview=True" not in source\n    assert source.count("fast_preview=False") >= 2\n''', encoding='utf-8')
