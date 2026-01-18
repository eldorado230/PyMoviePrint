# PyMoviePrint 

PyMoviePrint is a Python application that creates "movie prints," also known as contact sheets or thumbnail indexes, from your video files. It offers both a graphical user interface (GUI) for ease of use and a command-line interface (CLI) for scripting and batch processing.

For a detailed guide on how to use all the features, please see the [User Guide](USER_GUIDE.md).

Current version: **1.0.0**

## Features

* **Graphical User Interface (GUI)**:
    * Modern, dark-themed interface.
    * **Live Preview**: Generate low-res previews to tweak settings before processing.
    * **Scrubbing**: Click and drag on specific thumbnails in the preview to scrub through the video and select the perfect frame.
    * **Drag-and-Drop**: Support for dragging files and folders directly into the application.
* **Command-Line Interface (CLI)**: Enables scripting, automation, and batch processing.
* **Frame Extraction Modes**:
    * **Interval Mode**: Extracts frames at regular time or frame intervals.
    * **Shot Detection Mode**: Utilizes PySceneDetect to extract frames at detected shot boundaries.
* **HDR Support (Tone Mapping)**: Automatically or manually convert washed-out HDR (High Dynamic Range) colors to standard SDR using customizable algorithms (Hable, Reinhard, Mobius).
* **Performance**:
    * **GPU Acceleration**: Option to use NVIDIA CUDA hardware acceleration (requires compatible FFmpeg setup).
* **Layout Modes**:
    * **Grid Layout**: Arranges thumbnails in a standard grid.
    * **Timeline Layout**: Arranges thumbnails proportionally to shot duration (requires shot detection mode).
* **Customization**:
    * **Frame Info / OSD**: Overlay timecodes or frame numbers directly onto thumbnails with customizable position, color, and size.
    * **Styling**: Adjustable padding, grid margins, background color, and **rounded corners**.
    * **Rotation**: Rotate thumbnails by 90, 180, or 270 degrees.
* **Batch Processing**: Process multiple video files or entire directories recursively.
* **Naming Control**: Choose between appending suffixes to original filenames or defining custom fixed filenames.

## Setup / Installation

1.  **Python Version**: Python 3.8 or newer is recommended.

2.  **Create a Virtual Environment** (Recommended):
    ```bash
    python -m venv .venv
    ```
    Activate the virtual environment:
    * On Windows:
        ```bash
        .venv\Scripts\activate
        ```
    * On macOS/Linux:
        ```bash
        source .venv/bin/activate
        ```

3.  **Install Dependencies**:
    Ensure your virtual environment is activated, then run:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Key Dependencies**:
    * `opencv-python`: Video processing.
    * `PySceneDetect`: Shot boundary detection.
    * `Pillow`: Image manipulation.
    * `customtkinter`: Modern GUI elements.
    * `tkinterdnd2`: Drag-and-drop support.

5.  **FFmpeg Requirement**:
    **Crucial:** This tool relies heavily on **FFmpeg** for frame extraction, HDR tone mapping, and GPU acceleration. Ensure `ffmpeg` and `ffprobe` are in your system PATH.
    * To use **GPU acceleration**, you need an FFmpeg build compiled with `--enable-cuda-nvcc` and `--enable-libnpp`.
    * To use high-quality **HDR tone mapping**, you need an FFmpeg build with `--enable-libzimg` (zscale).

## Usage

### GUI (`movieprint_gui.py`)

1.  **Run the GUI**:
    ```bash
    python movieprint_gui.py
    ```
2.  **Workflow**:
    * **Input**: Drag videos onto the window or use the "Single Source" / "Batch Queue" tabs.
    * **Preview**: Click "PREVIEW" to generate a draft.
    * **Scrub**: In the preview window, click and drag left/right on any thumbnail to change the specific timestamp for that cell.
    * **Settings**:
        * **Layout**: Configure columns, rows, and margins.
        * **Advanced**: Set extraction modes, shot thresholds, and naming schemes.
        * **HDR & Color**: Enable tone mapping if your video looks washed out.
    * **Generate**: Click "APPLY / SAVE" to render the full-resolution output.

### Command-Line Interface (`movieprint_maker.py`)

The CLI is ideal for automation.

**Examples**:

* **Simple grid (5x5) for a single video**:
    ```bash
    python movieprint_maker.py my_video.mp4 ./output --columns 5 --rows 5
    ```

* **Timeline layout using shot detection**:
    ```bash
    python movieprint_maker.py movie.mov ./output --extraction_mode shot --layout_mode timeline --target_row_height 120
    ```

* **Batch process a folder with HDR Tone Mapping and GPU**:
    ```bash
    python movieprint_maker.py ./videos ./output --recursive_scan --hdr_tonemap --hdr_algorithm hable --use_gpu
    ```

* **Stylized print with rounded corners and frame info overlay**:
    ```bash
    python movieprint_maker.py clip.mp4 ./output --rounded_corners 15 --padding 10 --frame_info_show --frame_info_position bottom_right
    ```

## Command-Line Options (`movieprint_maker.py`)

**Input/Output**:
* `input_paths`: Video files or directories.
* `output_dir`: Directory for saved images.
* `--naming_mode {suffix,custom}`: Naming strategy. Default: `suffix`.
* `--output_filename_suffix`: Text appended to filename (e.g., `_movieprint`).
* `--output_filename`: Custom filename (used if naming_mode is 'custom').

**Batch**:
* `--video_extensions`: Comma-separated list (default: `.mp4,.avi,.mov,.mkv,.flv,.wmv`).
* `--recursive_scan`: Scan directories recursively.

**Extraction**:
* `--extraction_mode {interval,shot}`: Default `interval`.
* `--interval_seconds`: Seconds between frames.
* `--interval_frames`: Frames between captures.
* `--shot_threshold`: Sensitivity for shot detection (Default: 27.0).
* `--start_time`, `--end_time`: Time range to process.

**Layout**:
* `--layout_mode {grid,timeline}`: Default `grid`.
* `--columns`, `--rows`: Grid dimensions.
* `--target_thumbnail_width`: Force a specific width (px) per thumbnail.
* `--target_row_height`: Height for timeline rows.

**Styling & Visuals**:
* `--padding`: Pixels between images.
* `--grid_margin`: Outer margin of the image.
* `--background_color`: Hex color (e.g., `#FFFFFF`).
* `--rounded_corners`: Radius for corner rounding (0 = square).
* `--rotate_thumbnails {0,90,180,270}`: Rotation degrees.
* `--detect_faces`: Enable Haar Cascade face detection.

**Frame Info / OSD (On-Screen Display)**:
* `--frame_info_show`: Enable text overlay on thumbnails.
* `--frame_info_timecode_or_frame {timecode,frame}`: content to display.
* `--frame_info_position {top_left,top_right,bottom_left,bottom_right}`.
* `--frame_info_font_color`: Hex color.
* `--frame_info_bg_color`: Hex color for text background box.

**HDR & Performance**:
* `--hdr_tonemap`: Enable HDR to SDR conversion.
* `--hdr_algorithm {hable,reinhard,mobius}`: Tone mapping algorithm.
* `--use_gpu`: Attempt to use hardware acceleration (CUDA).
* `--temp_dir`: Custom directory for extracted frames.

## GUI Settings Persistence

The GUI automatically saves your preferences (layout, colors, extraction settings) to `movieprint_gui_settings.json` upon exit and restores them on launch.

## Contributing
Contributions are welcome! Please fork the repository, make your changes on a separate branch, and submit a pull request.