# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import sys
import os

block_cipher = None

# Collect all data/binaries for tkinterdnd2
# tkinterdnd2 binaries are needed for the drag-and-drop functionality
tmp_ret = collect_all('tkinterdnd2')
datas = tmp_ret[0]
binaries = tmp_ret[1]
hiddenimports = tmp_ret[2]

# Add other potentially hidden imports
hiddenimports += ['scenedetect', 'cv2', 'PIL', 'tkinter', 'tkinter.filedialog', 'tkinter.messagebox', 'tkinter.colorchooser', 'tkinter.scrolledtext', 'tkinter.ttk']

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
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MoviePrint',
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
        name='MoviePrint.app',
        icon=None,
        bundle_identifier='com.movieprint.gui',
    )
