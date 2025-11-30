# PyMoviePrint

PyMoviePrint is a Python application designed to create "movie prints" (also known as contact sheets or thumbnail indexes) from video files. It provides both a modern Graphical User Interface (GUI) built with `customtkinter` and a powerful Command-Line Interface (CLI) for batch processing and automation.

The application allows users to extract frames based on intervals or scene detection, lay them out in customizable grids or timelines, and export the results as high-quality images.

## Features

*   **Dual Interface**:
    *   **GUI**: Intuitive interface with drag-and-drop support, real-time preview, live scrubbing, and visual customization.
    *   **CLI**: Robust command-line tool for scripting and batch processing.
*   **Flexible Extraction**:
    *   **Interval Mode**: Extract frames at fixed time or frame intervals.
    *   **Shot Detection**: Automatically detect scene changes and extract representative frames (requires `PySceneDetect`).
    *   **Manual Scrubbing**: (GUI only) Interactively select specific frames by scrubbing over thumbnails.
*   **Customizable Layouts**:
    *   **Grid Layout**: Standard rows and columns.
    *   **Timeline Layout**: Variable-width thumbnails representing scene duration (best with Shot Detection).
*   **Rich Styling**:
    *   Adjustable padding, margins, and background colors.
    *   Rounded corners for thumbnails.
    *   Customizable text overlays (timecode, frame number, file info).
    *   Thumbnail rotation (0, 90, 180, 270 degrees).
*   **Advanced Processing**:
    *   **Face Detection**: Automatically highlight or focus on faces (requires OpenCV Haar cascades).
    *   **GPU Acceleration**: Support for FFmpeg hardware acceleration (NVDEC/CUDA) where available.
    *   **Time Segmentation**: Process only specific segments of a video.
    *   **Smart Resizing**: Output file size limits and quality controls.
*   **Batch Operations**: Process entire directories recursively with custom filtering.

## Installation

### Prerequisites

*   **Python 3.8+**
*   **FFmpeg**: Required for video processing. Must be installed and accessible in your system's PATH.
    *   *Windows*: Download from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) or [BtbN](https://github.com/BtbN/FFmpeg-Builds/releases).
    *   *macOS*: `brew install ffmpeg`
    *   *Linux*: `sudo apt-get install ffmpeg`

### Setup

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/yourusername/pymovieprint.git
    cd pymovieprint
    ```

2.  **Create a Virtual Environment** (Recommended):
    ```bash
    python -m venv .venv
    # Windows
    .venv\Scripts\activate
    # macOS/Linux
    source .venv/bin/activate
    ```

3.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
    *Note: `requirements.txt` should include `customtkinter`, `opencv-python`, `Pillow`, `scenedetect`, and `tkinterdnd2`.*

## Usage

### Graphical User Interface (GUI)

Launch the GUI with:
```bash
python movieprint_gui.py
```

*   **Input**: Drag and drop video files onto the input field or the landing area.
*   **Preview**: Click "PREVIEW" to generate a draft layout.
*   **Scrubbing**: Click and drag on any thumbnail in the preview to scrub through the video and select a different frame for that slot.
*   **Customization**: Use the sidebar to adjust columns, rows, margins, colors, and more.
*   **Export**: Click "APPLY / SAVE" to generate the final high-resolution image.

### Command-Line Interface (CLI)

The CLI is handled by `movieprint_maker.py`.

**Basic Syntax**:
```bash
python movieprint_maker.py [INPUT_PATHS] [OUTPUT_DIR] [OPTIONS]
```

**Examples**:

1.  **Simple 5x5 Grid**:
    ```bash
    python movieprint_maker.py video.mp4 ./output --columns 5 --rows 5
    ```

2.  **Shot Detection with Timeline Layout**:
    ```bash
    python movieprint_maker.py movie.mkv ./output --extraction_mode shot --layout_mode timeline --shot_threshold 30
    ```

3.  **Batch Process a Directory**:
    ```bash
    python movieprint_maker.py ./my_videos ./output --recursive_scan --columns 4 --output_filename_suffix _contact_sheet
    ```

4.  **Save Alongside Source Video**:
    ```bash
    python movieprint_maker.py video.mp4 . --save_alongside
    ```

**Key Arguments**:

*   `--columns`, `--rows`: Set grid dimensions.
*   `--interval_seconds`: Time between frames (Interval mode).
*   `--shot_threshold`: Sensitivity for scene detection (Shot mode).
*   `--start_time`, `--end_time`: Process a specific segment (e.g., "00:05:00").
*   `--background_color`: Hex code for background (e.g., "#000000").
*   `--detect_faces`: Enable face detection overlays.
*   `--use_gpu`: Attempt to use hardware acceleration.

For a full list of options, run:
```bash
python movieprint_maker.py --help
```

## Project Structure

*   `movieprint_gui.py`: Main entry point for the GUI. Handles UI logic and interaction.
*   `movieprint_maker.py`: CLI entry point and orchestration logic. Bridges the gap between user settings and processing modules.
*   `video_processing.py`: Handles all video interaction (extraction, scrubbing, FFmpeg calls).
*   `image_grid.py`: Handles image composition, resizing, and drawing of the final contact sheet.
*   `state_manager.py`: Manages application state, settings data structures, and undo/redo history.
*   `version.py`: Contains version information.

## Contributing

Contributions are welcome! Please follow these steps:
1.  Fork the repository.
2.  Create a feature branch (`git checkout -b feature/AmazingFeature`).
3.  Commit your changes (`git commit -m 'Add AmazingFeature'`).
4.  Push to the branch (`git push origin feature/AmazingFeature`).
5.  Open a Pull Request.

Please ensure all new functions and classes include docstrings.

## License

[MIT License](LICENSE) (Assuming standard open source license, please verify).
