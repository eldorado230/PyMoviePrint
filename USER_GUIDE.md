PyMoviePrint

PyMoviePrint is a Python application that creates "movie prints" (also known as contact sheets, thumbnail indexes, or storyboards) from your video files. It bridges the gap between simple screenshot tools and professional video analysis software.

It offers both a Graphical User Interface (GUI) for ease of use and a Command-Line Interface (CLI) for scripting and batch processing.

Current version: 1.0.0

Features

Dual Interface:

GUI: Modern, dark-themed interface with Live Preview, Scrubbing (drag to find the perfect frame), and Drag-and-Drop.

CLI: Full automation support for batch processing servers or scripts.

Smart Layouts:

Grid: Standard rows and columns (e.g., 5x5).

Timeline: Thumbnails vary in width based on shot duration (requires Shot Detection).

Smart Fitting: Force the final image to exact dimensions (e.g., 1920x1080) regardless of grid size.

Intelligent Extraction:

Interval Mode: Capture frames every X seconds or N frames.

Shot Detection: Uses PySceneDetect to automatically find cuts and extract the main frame of every scene.

HDR to SDR Tone Mapping:

Automatically detects HDR (High Dynamic Range) content and tone-maps it to SDR so colors don't look washed out. Supports algorithms: hable, reinhard, mobius.

Visual Customization:

Styling: Rounded corners, custom padding, background colors, and rotation.

Info Overlays: Overlay Timecodes, Frame Numbers, or file metadata headers directly onto the image.

Performance:

GPU Acceleration: Supports NVIDIA CUDA (NVDEC) for fast decoding (requires compatible FFmpeg).

Batch Processing: Recursive directory scanning with overwrite protection (skip existing files).

Installation

Prerequisites

Python 3.8+

FFmpeg: Must be installed and in your system PATH.

Optional: For GPU support, use an FFmpeg build with --enable-cuda-nvcc.

Optional: For HDR tone mapping, use an FFmpeg build with --enable-libzimg.

Setup

# 1. Create virtual environment
python -m venv .venv

# 2. Activate it
# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt


Usage

Graphical Interface (GUI)

Run the application:

python movieprint_gui.py


Preview: Drag a video in, click "Preview".

Scrub: Click and drag on any thumbnail in the preview to change that specific frame.

Save: Click "Apply / Save" to render the high-quality output.

Command-Line Interface (CLI)

The CLI is ideal for automation.

Basic Grid (5x5)

python movieprint_maker.py input.mp4 ./output --columns 5 --rows 5


Shot Detection with Timecodes

python movieprint_maker.py input.mp4 ./output --extraction_mode shot --frame_info_show


Wallpaper Mode (Fixed 1920x1080 Output)

python movieprint_maker.py input.mp4 ./output --fit_to_output_params --output_width 1920 --output_height 1080


Batch Process a Folder (Recursive)

python movieprint_maker.py ./my_collection ./output --recursive_scan --overwrite_mode skip


CLI Options Reference

Input/Output

input_paths: Video files or directories.

output_dir: Directory for saved images.

--naming_mode {suffix,custom}: Naming strategy. Default: suffix.

--output_filename_suffix: Text appended to filename.

--output_filename: Custom filename (used if naming_mode is 'custom').

--overwrite_mode {overwrite,skip}: Action if output file exists.

Batch

--video_extensions: Comma-separated list (default: .mp4,.avi,.mov,.mkv,.flv,.wmv).

--recursive_scan: Scan directories recursively.

Extraction

--extraction_mode {interval,shot}: Default interval.

--interval_seconds: Seconds between frames.

--interval_frames: Frames between captures.

--shot_threshold: Sensitivity for shot detection (Default: 27.0).

--start_time, --end_time: Time range to process.

Layout

--layout_mode {grid,timeline}: Default grid.

--columns, --rows: Grid dimensions.

--target_thumbnail_width: Force a specific width (px) per thumbnail.

--target_row_height: Height for timeline rows.

--fit_to_output_params: Force the final image to match output_width/height.

--output_width: Target image width (default: 1920).

--output_height: Target image height (default: 1080).

Styling & Visuals

--padding: Pixels between images.

--grid_margin: Outer margin of the image.

--background_color: Hex color (e.g., #FFFFFF).

--rounded_corners: Radius for corner rounding (0 = square).

--rotate_thumbnails {0,90,180,270}: Rotation degrees.

--detect_faces: Enable Haar Cascade face detection.

--show_header: Show a header bar with file info at the top.

--output_quality: JPEG Quality (1-100). Default: 95.

--max_output_filesize_kb: Attempt to reduce quality to meet target KB size.

Frame Info / OSD

--frame_info_show: Enable text overlay on thumbnails.

--frame_info_timecode_or_frame {timecode,frame}: content to display.

--frame_info_position {top_left,top_right,bottom_left,bottom_right}.

--frame_info_font_color: Hex color.

--frame_info_bg_color: Hex color for text background box.

HDR & Performance

--hdr_tonemap: Enable HDR to SDR conversion.

--hdr_algorithm {hable,reinhard,mobius}: Tone mapping algorithm.

--use_gpu: Attempt to use hardware acceleration (CUDA).

--temp_dir: Custom directory for extracted frames.

License

MIT License