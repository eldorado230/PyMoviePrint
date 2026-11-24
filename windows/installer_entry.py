"""Initialise the per-user Windows installation before starting the GUI."""

import argparse
import ctypes
import json
import logging
import os
from pathlib import Path
import sys
import tempfile


SETTINGS_NAME = 'movieprint_gui_settings.json'
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv'}


def migrate_settings(source, destination):
    """Copy the prototype settings once, even if two launches race."""
    if destination.exists():
        return False
    temporary_path = None
    try:
        try:
            payload = source.read_bytes()
        except FileNotFoundError:
            return False
        if not isinstance(json.loads(payload.decode('utf-8')), dict):
            raise ValueError('expected a JSON object')
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.settings-', delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        try:
            os.link(temporary_path, destination)
        except FileExistsError:
            return False
        return True
    except (OSError, ValueError) as error:
        logging.getLogger(__name__).warning('Could not migrate prototype settings: %s', error)
        return False
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as error:
                logging.getLogger(__name__).warning('Could not remove temporary settings: %s', error)


def preview_arguments(arguments):
    parser = argparse.ArgumentParser(exit_on_error=False)
    parser.add_argument('--preview', type=Path)
    options, extra = parser.parse_known_args(arguments)
    if extra:
        raise ValueError('Select one video to create a contact sheet.')
    path = options.preview
    if path is not None and (
        not path.is_absolute() or path.suffix.lower() not in VIDEO_EXTENSIONS or not path.is_file()
    ):
        raise ValueError('Select an existing MP4, AVI, MOV, MKV, FLV, or WMV video.')
    return path


def main():
    install_dir = Path(sys.executable).resolve().parent
    media_dir = install_dir / 'ffmpeg'
    tools = {name: media_dir / f'{name}.exe' for name in ('ffmpeg', 'ffprobe', 'ffplay')}
    try:
        preview = preview_arguments(sys.argv[1:])
        for tool in tools.values():
            if not tool.is_file():
                raise FileNotFoundError(f'Installed media executable missing: {tool.name}. Reinstall PyMoviePrint.')
        local_data = Path(os.environ['LOCALAPPDATA'])
        profile = local_data / 'PyMoviePrint'
        profile.mkdir(parents=True, exist_ok=True)
        import movieprint_gui as gui

        video = gui.DependencyManager.video_processing
        if video is not None:
            video.FFMPEG_BIN = os.fspath(tools['ffmpeg'])
            video.FFPROBE_BIN = os.fspath(tools['ffprobe'])
            video.FFPLAY_BIN = os.fspath(tools['ffplay'])
        gui.SETTINGS_FILE = profile / SETTINGS_NAME
        gui.setup_file_logging(profile / 'logs')
        migrate_settings(local_data / 'PyMoviePrintPrototype' / SETTINGS_NAME, gui.SETTINGS_FILE)
        app = gui.MoviePrintApp()
        if preview is not None:
            app.after_idle(app._add_preview_paths, [os.fspath(preview)])
        app.mainloop()
    except Exception as error:
        ctypes.windll.user32.MessageBoxW(None, str(error), 'PyMoviePrint startup error', 0x10)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
