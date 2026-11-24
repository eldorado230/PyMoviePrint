"""Exercise the actual installer and installed Windows UI on a disposable desktop."""

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import winreg

from PIL import Image, ImageGrab
import psutil
import pywintypes
import win32api
import win32con
import win32event
import win32gui
import win32process
import win32security
from win32com.shell import shell, shellcon
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage import FileAccessMode, StorageFile


UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{139498E8-C648-4E75-839A-2B924CD6DC1C}_is1'
VERB = 'PyMoviePrint.ContactSheet'
EXTENSIONS = ('.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv')


def wait_for(check, label, seconds=35):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.15)
    raise AssertionError(f'Timed out waiting for {label}')


def user_installation():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            return winreg.QueryValueEx(key, 'DisplayVersion')[0]
    except FileNotFoundError:
        return None


def verb_key(extension):
    return fr'Software\Classes\SystemFileAssociations\{extension}\shell\{VERB}'


def verb_value(extension, name='', command=False):
    key_path = verb_key(extension) + (r'\command' if command else '')
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except FileNotFoundError:
        return None


def shell_preview(video, environment):
    # The Shell resolves the registered verb and invokes it with the selected file.
    previous = {key: os.environ.get(key) for key in ('LOCALAPPDATA', 'PATH', 'SDL_AUDIODRIVER')}
    try:
        os.environ.update({key: environment[key] for key in previous})
        result = shell.ShellExecuteEx(
            fMask=shellcon.SEE_MASK_NOCLOSEPROCESS | shellcon.SEE_MASK_FLAG_DDEWAIT,
            lpVerb=VERB, lpFile=str(video), lpDirectory=str(video.parent), nShow=win32con.SW_SHOWNORMAL,
        )
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    handle = result['hProcess']
    assert handle is not None, 'The Explorer action did not start an application process.'
    try:
        return psutil.Process(win32process.GetProcessId(handle))
    finally:
        handle.Close()


def installer(executable, arguments, environment, log):
    current = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_ALL_ACCESS)
    admin_sid = win32security.CreateWellKnownSid(win32security.WinBuiltinAdministratorsSid, None)
    restricted = win32security.CreateRestrictedToken(current, 0x5, [(admin_sid, 0)], [], [])
    groups = win32security.GetTokenInformation(restricted, win32security.TokenGroups)
    assert not any(sid == admin_sid and flags & 4 for sid, flags in groups), 'Installer token still has enabled Administrators membership'
    command = [str(executable), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', f'/LOG={log}', *arguments]
    process, thread, _, _ = win32process.CreateProcessAsUser(
        restricted, str(executable), subprocess.list2cmdline(command), None, None, False,
        win32con.CREATE_UNICODE_ENVIRONMENT, environment, str(log.parent), win32process.STARTUPINFO(),
    )
    thread.Close()
    try:
        if win32event.WaitForSingleObject(process, 120000) != win32event.WAIT_OBJECT_0:
            win32api.TerminateProcess(process, 1)
            raise AssertionError(f'Installer did not exit: {log}')
        code = win32process.GetExitCodeProcess(process)
        assert code == 0, f'Installer exited with {code}: {log}'
    finally:
        process.Close()
        restricted.Close()
        current.Close()


def find_window(pid, prefix):
    candidates = []
    def inspect(window, _):
        _, owner = win32process.GetWindowThreadProcessId(window)
        if owner == pid and win32gui.IsWindowVisible(window) and win32gui.GetWindowText(window).startswith(prefix):
            candidates.append(window)
    win32gui.EnumWindows(inspect, None)
    return candidates[0] if candidates else None


async def recognise(engine, screenshot):
    image = await StorageFile.get_file_from_path_async(str(screenshot))
    stream = await image.open_async(FileAccessMode.READ)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    return await engine.recognize_async(bitmap)


def mouse_click(point):
    win32api.SetCursorPos(point)
    time.sleep(.15)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def focus_window(window):
    if win32gui.GetForegroundWindow() == window:
        return
    win32gui.ShowWindow(window, win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(window)
    except pywintypes.error:
        flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
        win32gui.SetWindowPos(window, win32con.HWND_TOPMOST, 0, 0, 0, 0, flags)
        try:
            left, top, _, _ = win32gui.GetWindowRect(window)
            mouse_click((left + 100, top + 18))
        finally:
            win32gui.SetWindowPos(window, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, flags)
    wait_for(lambda: win32gui.GetForegroundWindow() == window, 'packaged window focus', 5)


def find_label(engine, window, label, path):
    def detect():
        focus_window(window)
        x, y, right, bottom = win32gui.GetWindowRect(window)
        ImageGrab.grab(bbox=(max(x, 0), max(y, 0), right, bottom)).save(path)
        result = asyncio.run(recognise(engine, path))
        tokens = label.lower().split()
        for line in result.lines:
            words = list(line.words)
            texts = [word.text.lower().strip('.,:') for word in words]
            for index in range(len(texts) - len(tokens) + 1):
                if texts[index:index + len(tokens)] == tokens:
                    first = words[index].bounding_rect
                    last = words[index + len(tokens) - 1].bounding_rect
                    return (
                        max(x, 0) + round((first.x + last.x + last.width) / 2),
                        max(y, 0) + round(first.y + first.height / 2),
                    )
    return wait_for(detect, f'visible {label} (screenshot: {path})', 24)


def click_label(engine, window, label, path):
    point = find_label(engine, window, label, path)
    mouse_click(point)


def edit_preview(engine, window, screenshot):
    focus_window(window)
    left, top, right, bottom = win32gui.GetWindowRect(window)
    frame = ImageGrab.grab(bbox=(left, top, right, bottom)).convert('RGB')
    width, height = frame.size
    pixels = frame.load()
    # The FFmpeg colour-bar fixture has saturated reds that do not occur in the neutral UI.
    point = next((
        (left + x, top + y)
        for y in range(height // 6, 5 * height // 6, 4)
        for x in range(width // 5, 3 * width // 4, 4)
        if all(r > 215 and g < 65 and b < 65 for r, g, b in (pixels[x, y], pixels[x + 3, y]))
    ), None)
    assert point is not None, 'No test video frame visible in the preview.'
    mouse_click(point)
    find_label(engine, window, 'Included in export', screenshot)
    click_label(engine, window, 'Hide', screenshot)
    find_label(engine, window, 'Hidden from export', screenshot)
    click_label(engine, window, 'Hide', screenshot)
    find_label(engine, window, 'Included in export', screenshot)


def open_player(engine, window, path):
    # At 100% DPI Windows OCR can omit the narrow Fit/Player button labels.
    # The Zoom label is a visible anchor in the same toolbar row.
    x, y = find_label(engine, window, 'Zoom', path)
    scale = ctypes.windll.user32.GetDpiForWindow(window) / 96
    mouse_click((x + round(275 * scale), y))


def check_playback(engine, window, app, ffplay, video, environment, log):
    root = video.parent
    open_player(engine, window, root / 'player-control.png')
    player = wait_for(lambda: find_window(app.pid, 'Player - '), 'bundled video player window')
    monitor = win32api.MonitorFromWindow(player, win32con.MONITOR_DEFAULTTONEAREST)
    left, top, right, bottom = win32api.GetMonitorInfo(monitor)['Work']
    x, y, player_right, player_bottom = win32gui.GetWindowRect(player)
    # The player's natural size can put its footer below the runner's small desktop.
    win32gui.MoveWindow(player, left, top, min(player_right - x, right - left),
                        min(player_bottom - y, bottom - top), True)
    click_label(engine, player, 'Audio player', root / 'audio-control.png')
    playback = wait_for(lambda: next(
        (process for process in app.children() if Path(process.exe()) == ffplay), None
    ), 'installed FFplay child')
    assert playback.wait(timeout=15) == 0
    assert 'Audio player failed' not in log.read_text(encoding='utf-8')
    subprocess.run([ffplay, '-v', 'error', '-autoexit', '-nodisp', str(video)], check=True,
                   env=environment, timeout=15, capture_output=True)
    print('Candidate FFplay completed GUI audio/video playback and audio-only decoding with the SDL dummy device.')
    win32gui.PostMessage(player, win32con.WM_CLOSE, 0, 0)
    wait_for(lambda: not win32gui.IsWindowVisible(player), 'player closed')


def close_window(app, window):
    win32gui.PostMessage(window, win32con.WM_CLOSE, 0, 0)
    assert app.wait(timeout=20) == 0


def dismiss_export_confirmation(app):
    dialog = wait_for(lambda: find_window(app.pid, 'Generation Complete'), 'successful export confirmation')
    win32gui.PostMessage(dialog, win32con.WM_CLOSE, 0, 0)
    wait_for(lambda: not win32gui.IsWindowVisible(dialog), 'export confirmation dismissed')


def export_png(engine, window, screenshot, log, result):
    marker = 'Starting PyMoviePrint generation process'
    initial = log.read_text(encoding='utf-8').count(marker) if log.exists() else 0
    for _ in range(2):
        click_label(engine, window, 'Export movieprint', screenshot)
        try:
            wait_for(lambda: result.exists() or (log.exists() and log.read_text(encoding='utf-8').count(marker) > initial),
                     'export to begin', 4)
            break
        except AssertionError:
            if result.exists():
                break
    wait_for(result.exists, 'packaged PNG export')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def isolated_environment(root):
    environment = dict(os.environ)
    environment.update(
        LOCALAPPDATA=str(root / 'profile'),
        PATH=os.pathsep.join([str(Path(os.environ['SystemRoot']) / 'System32'), os.environ['SystemRoot']]),
        SDL_AUDIODRIVER='dummy',
    )
    return environment


def main(root, baseline, setup):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from version import __version__

    print(f'Candidate installer SHA-256: {digest(setup)}')
    ctypes.windll.user32.SetProcessDPIAware()
    engine = OcrEngine.try_create_from_user_profile_languages()
    assert engine is not None, 'The Windows runner lacks an OCR language.'
    assert user_installation() is None, 'Use a disposable Windows user with no installed PyMoviePrint.'
    root.mkdir()
    local_data = root / 'profile'
    local_data.mkdir()
    install = local_data / 'Programs' / 'PyMoviePrint'
    profile = local_data / 'PyMoviePrint'
    environment = isolated_environment(root)
    for dependency in ('python.exe', 'ffmpeg.exe', 'ffprobe.exe', 'ffplay.exe'):
        assert shutil.which(dependency, path=environment['PATH']) is None, dependency
    installer(baseline, [f'/DIR={install}'], environment, root / 'install.log')
    assert user_installation() == f'{__version__}.1'
    assert all(verb_value(extension, command=True) is None for extension in EXTENSIONS)
    ffmpeg, ffprobe, ffplay = (install / 'ffmpeg' / f'{name}.exe' for name in ('ffmpeg', 'ffprobe', 'ffplay'))
    video = root / 'Acceptance; Sample.mp4'
    subprocess.run([
        ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=240x144:rate=12',
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '6',
        '-c:v', 'mpeg4', '-c:a', 'aac', str(video),
    ], check=True, timeout=30, env=environment)
    probe = subprocess.check_output([
        ffprobe, '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'json', str(video)
    ], env=environment, timeout=20)
    assert {item['codec_type'] for item in json.loads(probe)['streams']} == {'video', 'audio'}

    settings = profile / 'movieprint_gui_settings.json'
    legacy_settings = local_data / 'PyMoviePrintPrototype' / settings.name
    legacy_settings.parent.mkdir()
    legacy_settings.write_text(json.dumps({
        'input_paths_list': [str(video)],
        'num_rows': 5, 'num_columns': 5, 'frame_format': 'png',
        'output_filename_suffix': '_acceptance', 'ui_theme': 'Teal',
    }), encoding='utf-8')
    legacy_checksum = digest(legacy_settings)
    log = profile / 'logs' / 'pymovieprint.log'
    installed_exe = install / 'PyMoviePrint.exe'
    first = subprocess.Popen([installed_exe], cwd=root, env=environment)
    try:
        window = wait_for(lambda: find_window(first.pid, f'PyMoviePrint v{__version__}'), 'installed PyMoviePrint window')
        click_label(engine, window, 'Build preview', root / 'build-preview.png')
        wait_for(lambda: log.exists() and 'Extracting frame 25/25' in log.read_text(encoding='utf-8'),
                 '25th thumbnail in the packaged app log')
        find_label(engine, window, 'Preview ready', root / 'contact-sheet-preview.png')
        result = root / 'Acceptance; Sample_acceptance.png'
        export_png(engine, window, root / 'export-control.png', log, result)
        with Image.open(result) as image:
            assert image.format == 'PNG'
            image.verify()
        with Image.open(result) as image:
            image.load()
            assert image.width >= 500 and image.height >= 300, image.size
            assert len(image.convert('RGB').resize((64, 64)).getcolors(4096)) > 64
            print(f'Packaged PNG export validated: {image.width}x{image.height}')
        dismiss_export_confirmation(first)
        close_window(first, window)
    finally:
        if first.poll() is None:
            first.terminate()
            first.wait(timeout=10)

    session_settings = json.loads(settings.read_text(encoding='utf-8'))
    assert session_settings['input_paths_list'] == [str(video)] and session_settings['frame_format'] == 'png'
    project = root / 'Existing work.pymovieprint.json'
    # Produce a genuine user project without modifying the installed application's files.
    import project_io
    from state_manager import ProjectState
    state = ProjectState(source_paths=[str(video)])
    project_io.save_project_json(str(project), state)
    original = {path: digest(path) for path in (settings, project, video, result)}
    foreign_command = 'existing-user-command'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, verb_key('.wmv') + r'\command') as key:
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, foreign_command)
    installer(setup, ['/TASKS=explorer'], environment, root / 'upgrade.log')
    assert user_installation() == f'{__version__}.2'
    assert all(digest(path) == checksum for path, checksum in original.items())
    for extension in EXTENSIONS[:-1]:
        assert verb_value(extension) == 'Create video contact sheet'
        assert verb_value(extension, 'MultiSelectModel') == 'Single'
        assert verb_value(extension, command=True) == f'"{installed_exe}" --preview "%1"'
    assert verb_value('.wmv', command=True) == foreign_command
    # Launch from the Shell and wait for a preview without clicking Build preview.
    result.unlink()
    second = shell_preview(video, environment)
    try:
        window = wait_for(lambda: find_window(second.pid, f'PyMoviePrint v{__version__}'), 'upgraded PyMoviePrint window')
        find_label(engine, window, 'Preview ready', root / 'explorer-preview.png')
        edit_preview(engine, window, root / 'explorer-edit.png')
        export_png(engine, window, root / 'export-after-upgrade.png', log, result)
        with Image.open(result) as image:
            assert image.format == 'PNG'
            image.load()
        dismiss_export_confirmation(second)
        check_playback(engine, window, second, ffplay, video, environment, log)
        close_window(second, window)
    finally:
        if second.is_running():
            second.terminate()
            second.wait(timeout=10)

    installer(setup, ['/MERGETASKS=!explorer'], environment, root / 'explorer-opt-out.log')
    assert all(verb_value(extension, command=True) is None for extension in EXTENSIONS[:-1])
    assert verb_value('.wmv', command=True) == foreign_command
    installer(setup, ['/TASKS=explorer'], environment, root / 'explorer-opt-in.log')
    assert verb_value('.mp4', command=True) == f'"{installed_exe}" --preview "%1"'
    uninstaller = list(install.glob('unins*.exe'))
    assert len(uninstaller) == 1
    installer(uninstaller[0], [], environment, root / 'uninstall.log')
    wait_for(lambda: not installed_exe.exists(), 'installed executable removed')
    assert user_installation() is None
    assert all(verb_value(extension, command=True) is None for extension in EXTENSIONS[:-1])
    assert verb_value('.wmv', command=True) == foreign_command
    assert all(digest(path) == original[path] for path in (project, video))
    assert json.loads(settings.read_text(encoding='utf-8'))['input_paths_list'] == [str(video)]
    assert digest(legacy_settings) == legacy_checksum
    assert result.is_file()
    print('Restricted-token install, upgrade, relaunch, and uninstall passed. Project, media, export, and settings survived.')
    print('Explorer opt-in, automatic preview via the registered Shell verb, opt-out, and uninstall passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('setup', type=Path)
    options = parser.parse_args()
    root = options.root.resolve()
    if root.exists():
        parser.error('The acceptance directory must not already exist.')
    try:
        main(root, options.baseline.resolve(), options.setup.resolve())
    finally:
        uninstaller = next((root / 'profile' / 'Programs' / 'PyMoviePrint').glob('unins*.exe'), None)
        if uninstaller is not None and user_installation() is not None:
            installer(uninstaller, [], isolated_environment(root), root / 'cleanup.log')
