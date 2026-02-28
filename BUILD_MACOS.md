# Build Guide: PyMoviePrint macOS App Bundle

This document explains how to package the GUI into a standalone macOS `.app` using PyInstaller.

---

## What This Produces

- Application bundle: `dist/PyMoviePrint.app`
- Entry point: `movieprint_gui.py`
- Build definition: `movieprint_gui.spec`

---

## Prerequisites

- macOS host machine
- Python 3.8+
- Xcode Command Line Tools recommended

Check basics:

```bash
python3 --version
xcode-select -p
```

---

## Fast Path (recommended)

Use the included helper script:

```bash
./build_macos.sh
```

The script will:
1. Create `.venv_build`
2. Install dependencies from `requirements.txt`
3. Install `pyinstaller`
4. Remove old `build/` and `dist/`
5. Build using `movieprint_gui.spec`

---

## Manual Build (step-by-step)

```bash
python3 -m venv .venv_build
source .venv_build/bin/activate
pip install -r requirements.txt
pip install pyinstaller
rm -rf build dist
pyinstaller movieprint_gui.spec
```

Output should appear under `dist/PyMoviePrint.app`.

---

## Verify the App Bundle

### Run from Finder
Open `dist/PyMoviePrint.app`.

### Run from Terminal (best for debugging)

```bash
dist/PyMoviePrint.app/Contents/MacOS/PyMoviePrint
```

This surfaces Python/runtime errors directly in terminal output.

---

## Common macOS Issues

### “App is damaged and can’t be opened”

Unsigned bundles may be quarantined by Gatekeeper.

```bash
xattr -cr dist/PyMoviePrint.app
```

### App opens then immediately closes

Run binary from terminal to inspect logs:

```bash
dist/PyMoviePrint.app/Contents/MacOS/PyMoviePrint
```

### Drag-and-drop missing in packaged app

The `.spec` file includes `tkinterdnd2` collection hooks; if packaging changes, verify those hooks remain.

---

## Optional: Code Signing & Notarization (distribution)

For wider distribution, sign and notarize with Apple developer credentials.
At minimum:
1. `codesign` the app bundle recursively.
2. Submit for notarization.
3. Staple notarization ticket.

(These steps are intentionally omitted from the default script because they require account-specific credentials.)

---

## Build Hygiene

- Keep packaging changes in `movieprint_gui.spec` version-controlled.
- Rebuild from a clean environment when dependency versions change.
- Test on a fresh macOS user account before sharing builds.
