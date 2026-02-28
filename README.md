# PyMoviePrint

PyMoviePrint generates high-quality **movie prints** (contact sheets / thumbnail indexes) from video files.
It ships with both:

- a desktop GUI (`movieprint_gui.py`) for interactive workflows, and
- a CLI (`movieprint_maker.py`) for repeatable automation and batch jobs.

Current version: **1.0.0**.

---

## Why PyMoviePrint

PyMoviePrint is designed for editors, archivists, assistants, and reviewers who need a visual summary of footage.
Compared to simple “every N seconds” contact-sheet scripts, it adds:

- **Multiple extraction strategies**: interval-based and shot-boundary-aware.
- **Layout control**: classic fixed-column grids and timeline-style rows.
- **HDR-aware processing**: optional tone mapping for cleaner SDR outputs from HDR sources.
- **Usable GUI workflow**: preview, iterative tuning, and per-thumbnail scrubbing.
- **Automation-first CLI**: deterministic output settings for batch pipelines.

---

## Core Feature Set

### Extraction
- **Interval mode**: extract at `--interval_seconds` or `--interval_frames`.
- **Shot mode**: use PySceneDetect to detect scene changes.
- **Range limiting**: process only a time span via `--start_time` and `--end_time`.

### Layout
- **Grid layout**: rows/columns with adjustable padding, margins, and thumbnail width.
- **Timeline layout**: shot-based rows with variable thumbnail widths.
- **Wallpaper mode**: `--fit_to_output_params` to force exact output dimensions.

### Visual Styling
- Background color, spacing, rounded corners, thumbnail rotation.
- Optional overlays (timecode/frame labels) and optional header.
- JPEG quality controls and post-save max filesize reduction.

### Performance & Compatibility
- FFmpeg-based extraction pipeline.
- Optional CUDA hardware decode path when available.
- Optional HDR→SDR tone mapping (Hable / Reinhard / Mobius).

---

## Installation

### 1) Requirements
- Python **3.8+**
- FFmpeg + ffprobe in `PATH`

### 2) Setup

```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3) Verify runtime tools

```bash
ffmpeg -version
ffprobe -version
python -c "import cv2, PIL, customtkinter; print('deps ok')"
```

---

## Quick Start

### GUI

```bash
python movieprint_gui.py
```

Recommended GUI flow:
1. Add source file(s).
2. Click **PREVIEW** for a draft render.
3. Scrub specific thumbnails by click-dragging in preview.
4. Tune layout/styling/HDR settings.
5. Click **APPLY / SAVE** for final output.

### CLI

```bash
python movieprint_maker.py <input_paths...> <output_dir> [options]
```

Examples:

```bash
# 5x5 grid, default naming suffix
python movieprint_maker.py clip.mp4 ./out --columns 5 --rows 5

# Shot-detected timeline print
python movieprint_maker.py movie.mov ./out \
  --extraction_mode shot --layout_mode timeline --target_row_height 120

# Fixed 1920x1080 output with HDR tone mapping
python movieprint_maker.py hdr_source.mkv ./out \
  --fit_to_output_params --output_width 1920 --output_height 1080 \
  --hdr_tonemap --hdr_algorithm hable

# Recursive batch with skip-existing policy
python movieprint_maker.py ./dailies ./out --recursive_scan --overwrite_mode skip
```

---

## Documentation Map

- **User Guide**: full GUI + CLI walkthrough and option reference in `USER_GUIDE.md`.
- **macOS packaging**: PyInstaller workflow in `BUILD_MACOS.md`.

---

## Project Architecture (Deep-Dive Summary)

- `movieprint_gui.py`: full CustomTkinter application, preview workflow, scrubbing handler, queued worker pattern.
- `movieprint_maker.py`: orchestration layer; argument parsing, input discovery, extraction mode routing, metadata output.
- `video_processing.py`: frame extraction engines (FFmpeg/OpenCV), shot detection integration, HDR probing/tone mapping path.
- `image_grid.py`: rendering engine for grid/timeline compositing, overlays, rounding, and file export.
- `state_manager.py`: GUI state dataclasses plus undo/redo snapshots.
- `movieprint_gui.spec` + `build_macos.sh`: packaging recipe for standalone macOS app.

---

## Known Operational Notes

- FFmpeg availability is critical; most extraction paths rely on it.
- Shot mode depends on PySceneDetect support in the environment.
- HDR tone mapping in shot mode is currently limited compared with interval/timestamp extraction workflows.
- For best deterministic outputs in automation, pin explicit values (rows/columns, dimensions, naming, overwrite mode).

---

## License

MIT
