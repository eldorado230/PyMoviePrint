# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import sys
import os


# Collect all data/binaries for tkinterdnd2
# tkinterdnd2 binaries are needed for the drag-and-drop functionality
tmp_ret = collect_all('tkinterdnd2')
datas = tmp_ret[0]
binaries = tmp_ret[1]
hiddenimports = tmp_ret[2]
ctk_data, ctk_binaries, ctk_imports = collect_all('customtkinter')
datas += ctk_data
datas += [(os.path.join(SPECPATH, 'assets', 'movieprint-studio-v1.png'), 'assets')]
binaries += ctk_binaries
hiddenimports += ctk_imports

# Add other potentially hidden imports
hiddenimports += ['scenedetect', 'cv2', 'PIL', 'tkinter', 'tkinter.filedialog', 'tkinter.messagebox', 'tkinter.colorchooser', 'tkinter.scrolledtext', 'tkinter.ttk']
hiddenimports += ['video_processing', 'image_grid', 'state_manager', 'project_io',
                  'movieprint_maker', 'workspace_tools', 'face_analysis', 'version']

a = Analysis(
    ['movieprint_gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PyMoviePrint',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='PyMoviePrint.app',
        icon=None,
        bundle_identifier='com.movieprint.gui',
    )
