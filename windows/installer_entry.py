"""Initialise the per-user Windows prototype before starting the existing GUI."""

import ctypes
import os
from pathlib import Path
import sys


def main():
    install_dir = Path(sys.executable).resolve().parent
    media_dir = install_dir / 'ffmpeg'
    tools = {name: media_dir / f'{name}.exe' for name in ('ffmpeg', 'ffprobe', 'ffplay')}
    try:
        for tool in tools.values():
            if not tool.is_file():
                raise FileNotFoundError(f'Installed media executable missing: {tool.name}. Reinstall PyMoviePrint.')
        profile = Path(os.environ['LOCALAPPDATA']) / 'PyMoviePrintPrototype'
        profile.mkdir(parents=True, exist_ok=True)
        import movieprint_gui as gui

        video = gui.DependencyManager.video_processing
        if video is not None:
            video.FFMPEG_BIN = os.fspath(tools['ffmpeg'])
            video.FFPROBE_BIN = os.fspath(tools['ffprobe'])
            video.FFPLAY_BIN = os.fspath(tools['ffplay'])
        gui.SETTINGS_FILE = profile / 'movieprint_gui_settings.json'
        gui.setup_file_logging(profile / 'logs')
        app = gui.MoviePrintApp()
        app.mainloop()
    except Exception as error:
        ctypes.windll.user32.MessageBoxW(None, str(error), 'PyMoviePrint startup error', 0x10)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
