# PyMoviePrint User Guide

This guide is a practical, end-to-end walkthrough of PyMoviePrint for both GUI users and CLI automation users.

- If you are new, read: **Concepts → GUI Quick Workflow → CLI Quick Recipes**.
- If you are scripting, jump to: **CLI Reference**.

---

## 1) Concepts You Should Know

### 1.1 Extraction Modes

- **Interval**: sample frames periodically (time-based or frame-based).
- **Shot**: detect scene boundaries and extract representative frames.

### 1.2 Layout Modes

- **Grid**: classic contact sheet with fixed columns (and optional fixed rows).
- **Timeline**: thumbnails arranged in rows where width can represent shot duration.

### 1.3 Fixed Output vs Dynamic Output

- **Dynamic (default)**: output size grows from source and layout settings.
- **Fixed output** (`--fit_to_output_params`): force final image dimensions (great for wallpapers, decks, templates).

### 1.4 HDR Handling

PyMoviePrint can detect HDR characteristics and optionally apply tone mapping so outputs don’t look washed out on SDR displays.

---

## 2) Installation & Environment

## 2.1 Prerequisites

- Python 3.8+
- `ffmpeg` and `ffprobe` available in PATH

## 2.2 Install

```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2.3 Validate

```bash
ffmpeg -version
ffprobe -version
python -c "import cv2, PIL, scenedetect, customtkinter; print('environment ok')"
```

---

## 3) GUI Workflow

Run:

```bash
python movieprint_gui.py
```

### 3.1 Typical Session

1. Add a single file or queue multiple files/folders.
2. Set extraction + layout settings.
3. Click **PREVIEW** to generate a draft.
4. Scrub thumbnails in preview to refine specific cells.
5. Apply style overlays, margins, color, HDR settings.
6. Click **APPLY / SAVE** for full output render.

### 3.2 Scrubbing (high-impact feature)

- Click and drag horizontally over a thumbnail in preview.
- Drag distance maps to time offset.
- Release to lock the chosen frame for that tile.

### 3.3 GUI Reliability Notes

- If drag-and-drop libraries are unavailable, the app still runs with fallback behavior.
- Logs are written under the user profile (`~/.pymovieprint/logs`) to assist debugging.

---

## 4) CLI Quick Recipes

Base command:

```bash
python movieprint_maker.py <input_paths...> <output_dir> [options]
```

### 4.1 Standard 5x5 print

```bash
python movieprint_maker.py input.mp4 ./output --columns 5 --rows 5
```

### 4.2 Exact 1920x1080 wallpaper export

```bash
python movieprint_maker.py input.mp4 ./output \
  --columns 5 --rows 5 \
  --fit_to_output_params --output_width 1920 --output_height 1080
```

### 4.3 Shot-detection timeline

```bash
python movieprint_maker.py input.mp4 ./output \
  --extraction_mode shot --layout_mode timeline --target_row_height 120
```

### 4.4 Batch recursive processing with skip policy

```bash
python movieprint_maker.py ./video_root ./output \
  --recursive_scan --overwrite_mode skip
```

### 4.5 HDR tone mapping + GPU decode attempt

```bash
python movieprint_maker.py hdr_input.mkv ./output \
  --hdr_tonemap --hdr_algorithm reinhard --use_gpu
```

---

## 5) CLI Reference (Organized)

## 5.1 Inputs & Output Naming

- `input_paths` (positional): one or more files/directories.
- `output_dir` (positional): destination folder.
- `--naming_mode {suffix,custom}`: filename strategy.
- `--output_filename_suffix`: append to source basename.
- `--output_filename`: explicit fixed name (custom mode).
- `--overwrite_mode {overwrite,skip}`: behavior when output exists.

## 5.2 Batch Controls

- `--video_extensions`: recognized extensions list.
- `--recursive_scan`: recurse into subfolders.

## 5.3 Time Segment

- `--start_time`: accepted examples: `75.5`, `01:15.5`, `00:01:15.5`.
- `--end_time`: same format; processing stops before this timestamp.

## 5.4 Extraction

- `--extraction_mode {interval,shot}`
- `--interval_seconds`
- `--interval_frames`
- `--shot_threshold` (scene detector sensitivity)
- `--exclude_frames` (interval mode)
- `--exclude_shots` (shot mode; 1-based indexing)

## 5.5 Layout

- `--layout_mode {grid,timeline}`
- `--columns`
- `--rows`
- `--target_thumbnail_width`
- `--max_frames_for_print`
- `--target_row_height` (timeline)
- `--fit_to_output_params`
- `--output_width`
- `--output_height`

## 5.6 Styling & Output

- `--padding`
- `--grid_margin`
- `--background_color`
- `--rounded_corners`
- `--rotate_thumbnails {0,90,180,270}`
- `--frame_format {jpg,png}`
- `--output_quality`
- `--max_output_filesize_kb`

## 5.7 Metadata, Overlays, and Header

- `--save_metadata_json`
- `--show_header`
- `--show_file_path`
- `--show_timecode`
- `--show_frame_num`
- `--frame_info_show`
- `--frame_info_timecode_or_frame`
- `--frame_info_position`
- `--frame_info_font_color`
- `--frame_info_bg_color`
- `--frame_info_size`
- `--frame_info_margin`

## 5.8 Performance / Advanced

- `--use_gpu` (CUDA decode when available)
- `--hdr_tonemap`
- `--hdr_algorithm {hable,reinhard,mobius}`
- `--temp_dir`
- `--fast` / `--draft` (preview-oriented extraction)
- `--detect_faces`
- `--haar_cascade_xml`

---

## 6) Suggested Presets

### Archival contact sheet (neutral)
- `--columns 6 --rows 6 --padding 4 --grid_margin 10 --output_quality 95`

### Fast review proof
- `--fast --columns 5 --rows 5 --output_quality 80`

### Presentation-ready clean output
- `--fit_to_output_params --output_width 1920 --output_height 1080 --rounded_corners 12 --padding 10 --show_header`

---

## 7) Troubleshooting

### 7.1 `ffmpeg` not found

Symptoms: extraction fails immediately.

Fix:

```bash
which ffmpeg
which ffprobe
```

Install FFmpeg and ensure PATH is configured.

### 7.2 Colors look flat/washed out

Likely HDR source without tone mapping.

Try:

```bash
--hdr_tonemap --hdr_algorithm hable
```

### 7.3 GPU flag gives no speedup

`--use_gpu` depends on FFmpeg build capabilities.
Use an FFmpeg build with CUDA/NVDEC support.

### 7.4 Shot detection unavailable

Ensure `scenedetect` is installed and importable in the environment.

### 7.5 Output size too large

- Reduce quality: `--output_quality 85`
- Enable size target: `--max_output_filesize_kb 1500`
- Reduce rows/columns or fixed resolution.

---

## 8) Deep-Dive: How Processing Flows Internally

1. Input paths are expanded into valid video files.
2. For each file, a temp directory is prepared.
3. Frames are extracted (manual timestamps / grid timestamps / interval / shot).
4. Optional per-frame transforms are applied (face detect metadata, rotation).
5. Final grid/timeline image is assembled and saved.
6. Optional JSON metadata is written.
7. Temp assets are cleaned unless a custom temp directory is retained.

This layered design keeps extraction, composition, and state management decoupled.
