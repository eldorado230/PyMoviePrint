# PyMoviePrint 

PyMoviePrint is a Python application that creates "movie prints," also known as contact sheets or thumbnail indexes, from your video files. It offers both a graphical user interface (GUI) for ease of use and a command-line interface (CLI) for scripting and batch processing.

For a detailed guide on how to use all the features, please see the [User Guide](USER_GUIDE.md).

Current version: **1.0.0**

## Features

*   **Graphical User Interface (GUI)**: For easy and interactive operation.
*   **Command-Line Interface (CLI)**: Enables scripting, automation, and batch processing.
*   **Frame Extraction Modes**:
    *   **Interval Mode**: Extracts frames at regular time or frame intervals.
    *   **Shot Detection Mode**: Utilizes PySceneDetect to extract frames at detected shot boundaries.
*   **Time Segmentation**: Specify custom start and end times for processing videos.
*   **Frame/Shot Exclusion**: Exclude specific unwanted frames (in interval mode) or shots (in shot mode).
*   **Layout Modes**:
    *   **Grid Layout**: Arranges thumbnails in a standard grid.
    *   **Timeline Layout**: Arranges thumbnails proportionally to shot duration (requires shot detection mode).
*   **Customizable Grid Layout**:
    *   Define the number of columns or rows.
    *   Set a target width for individual thumbnails (overrides automatic sizing).
    *   Limit the maximum number of frames to include in the print.
*   **Customizable Timeline Layout**:
    *   Define the target height for each row.
    *   Set the target width for the final output image.
*   **Styling**: Adjustable padding around thumbnails and customizable background color.
*   **Temporary Frame Format**: Choose between JPG or PNG for temporary extracted frames.
*   **Custom Temporary Directory**: Specify a directory for temporary frames (these will not be auto-cleaned).
*   **Thumbnail Rotation**: Rotate all thumbnails by 0, 90, 180, or 270 degrees clockwise.
*   **Face Detection**: Optionally detect faces in thumbnails (can be performance-intensive).
    *   Option to provide a custom Haar Cascade XML file.
*   **Metadata**: Saves detailed information about the generation process and included frames as a JSON sidecar file.
*   **Batch Processing**: Process multiple video files or entire directories.
    *   Recursive directory scanning option.
*   **Output Customization**: Define custom output filenames or suffixes for batch operations.
*   **File Size Targeting**: Optional CLI and GUI setting to limit the maximum size of the generated MoviePrint image.
*   **GUI Enhancements**:
    *   Drag-and-Drop support for input files and directories.
    *   Dynamic recalculation of frame extraction interval when 'Max Frames for Print' changes for a single selected video.
    *   Persistent GUI settings (saved to `movieprint_gui_settings.json`).
    *   "Reset to Defaults" button to revert GUI settings.

## Setup / Installation

1.  **Python Version**: Python 3.8 or newer is recommended.

2.  **Create a Virtual Environment** (Recommended):
    ```bash
    python -m venv .venv
    ```
    Activate the virtual environment:
    *   On Windows:
        ```bash
        .venv\Scripts\activate
        ```
    *   On macOS/Linux:
        ```bash
        source .venv/bin/activate
        ```

3.  **Install Dependencies**:
    Ensure your virtual environment is activated, then run:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Key Dependencies**:
    The `requirements.txt` file includes:
    *   `opencv-python`: For video processing and image manipulation.
    *   `PySceneDetect`: For shot detection capabilities.
    *   `Pillow`: For image manipulation and GUI display.
    *   `tkinterdnd2`: For drag-and-drop functionality in the GUI.

5.  **FFmpeg Note**:
    While not a direct Python dependency for installation, having FFmpeg available on your system can sometimes help OpenCV handle a wider variety of video codecs. For most common video formats (MP4, MOV, AVI, MKV), this should not be necessary as OpenCV often includes sufficient built-in codecs.

## Usage

### GUI (`movieprint_gui.py`)

1.  **Run the GUI**:
    ```bash
    python movieprint_gui.py
    ```
2.  **Overview**:
    *   **Input/Output Section**: Select video file(s), a directory of videos, or drag-and-drop them onto the input field. Choose an output directory for the generated MoviePrints.
    *   **Tabs for Settings**:
        *   **Extraction & Segment**: Choose extraction mode (Interval/Shot), set relevant parameters (interval duration, shot threshold), define start/end times, and specify frames/shots to exclude.
        *   **Layout**: Select layout mode (Grid/Timeline) and configure columns, thumbnail widths, row heights, max frames, etc.
        *   **Thumbnail Preview**: Displays a preview of the extracted thumbnails using the currently selected layout settings.
        *   **Batch & Output**: Configure output filename for single inputs, suffix for batch outputs, video extensions for scanning, and enable recursive scan.
        *   **Common & Advanced**: Set padding, background color, temporary frame format, rotation, custom temporary directory, face detection options, metadata saving, and an optional maximum output file size. Also contains the "Reset All Settings to Defaults" button.
    *   **Log Area**: Displays processing messages, warnings, and errors.
    *   **Generate MoviePrint Button**: Starts the MoviePrint generation process with the current settings.

### Command-Line Interface (`movieprint_maker.py`)

The CLI is ideal for batch processing, automation, or when a GUI is not needed.

1.  **Basic Structure**:
    ```bash
    python movieprint_maker.py <input_paths...> <output_dir> [options]
    ```
    *   `<input_paths...>`: One or more paths to video files or directories containing video files.
    *   `<output_dir>`: The directory where the generated MoviePrint images (and JSON metadata files) will be saved.

2.  **Examples**:

    *   **Simple grid (5 columns) for a single video, extracting every 10 seconds**:
        ```bash
        python movieprint_maker.py my_video.mp4 ./output --columns 5 --interval_seconds 10
        ```

    *   **Timeline layout using shot detection, with a target row height of 120px**:
        ```bash
        python movieprint_maker.py movie.mov ./output --extraction_mode shot --layout_mode timeline --target_row_height 120
        ```

    *   **Batch process a directory recursively, creating 4-column grids, 10px padding, PNG temp frames, and a custom suffix**:
        ```bash
        python movieprint_maker.py ./my_videos_folder ./output_prints --recursive_scan --columns 4 --padding 10 --frame_format png --output_filename_suffix _custom_print
        ```

    *   **Process a segment from 1:30 to 5:00, exclude specific frames (interval mode), and rotate thumbnails 90 degrees**:
        ```bash
        python movieprint_maker.py my_clip.mkv ./output --start_time 00:01:30 --end_time 00:05:00 --interval_seconds 5 --exclude_frames 150 151 200 --rotate_thumbnails 90
        ```

    *   **Specify target thumbnail width for grid layout and enable face detection**:
        ```bash
        python movieprint_maker.py short_film.mp4 ./output --layout_mode grid --target_thumbnail_width 320 --detect_faces
        ```

3.  **Output**:
    *   MoviePrint images are saved in the specified output directory.
    *   If `--save_metadata_json` is used, a JSON file with the same base name as the image, containing detailed metadata, will also be saved.

## Command-Line Options (`movieprint_maker.py`)

Below is a summary of the available command-line options, grouped by category.

**Input/Output Arguments**:

*   `input_paths`
    *   Type: string (one or more)
    *   Description: Video files or directories containing video files to process.
*   `output_dir`
    *   Type: string
    *   Description: Directory where the final MoviePrint image(s) and metadata will be saved.
*   `--output_filename_suffix SUFFIX`
    *   Type: string
    *   Default: `_movieprint`
    *   Description: Suffix to append to original video filenames when generating MoviePrints in batch mode.
*   `--output_filename FILENAME`
    *   Type: string
    *   Default: None
    *   Description: Specific output filename to use when processing a single input video file. Extension determines output format (e.g., `.png`, `.jpg`).

**Batch Processing Options**:

*   `--video_extensions EXTENSIONS`
    *   Type: string (comma-separated)
    *   Default: `.mp4,.avi,.mov,.mkv,.flv,.wmv`
    *   Description: Comma-separated list of video file extensions to look for when scanning directories.
*   `--recursive_scan`
    *   Action: store_true
    *   Description: If specified, scan input directories recursively for video files.

**Time Segment Options**:

*   `--start_time TIME`
    *   Type: string
    *   Default: None
    *   Description: Start time for processing (formats: HH:MM:SS, MM:SS, or seconds). Processes from the beginning if omitted.
*   `--end_time TIME`
    *   Type: string
    *   Default: None
    *   Description: End time for processing (formats: HH:MM:SS, MM:SS, or seconds). Processes until the end if omitted.

**Frame Extraction Options**:

*   `--extraction_mode {interval,shot}`
    *   Type: string
    *   Default: `interval`
    *   Choices: `interval`, `shot`
    *   Description: Method for selecting frames.
*   `--interval_seconds SECONDS`
    *   Type: float
    *   Default: None
    *   Description: For 'interval' mode: time in seconds between extracted frames.
*   `--interval_frames FRAMES`
    *   Type: int
    *   Default: None
    *   Description: For 'interval' mode: number of frames between extracted frames. If both seconds and frames interval are set, seconds interval is used.
*   `--shot_threshold VALUE`
    *   Type: float
    *   Default: `27.0`
    *   Description: For 'shot' mode: sensitivity for shot detection (lower value means more shots detected).
*   `--exclude_frames FRAME_NUM ...`
    *   Type: int (one or more)
    *   Default: None
    *   Description: List of absolute frame numbers to exclude (for 'interval' mode only).
*   `--exclude_shots SHOT_INDEX ...`
    *   Type: int (one or more)
    *   Default: None
    *   Description: List of 1-based shot indices to exclude (for 'shot' mode only).

**Layout Options**:

*   `--layout_mode {grid,timeline}`
    *   Type: string
    *   Default: `grid`
    *   Choices: `grid`, `timeline`
    *   Description: Layout arrangement for thumbnails. 'Timeline' mode requires '--extraction_mode shot'.
*   `--columns NUM_COLUMNS`
    *   Type: int
    *   Default: `5`
    *   Description: For 'grid' layout: number of columns for thumbnails.
*   `--rows NUM_ROWS`
    *   Type: int
    *   Default: None
    *   Description: For 'grid' layout: number of rows. Overrides columns when set.
*   `--target_thumbnail_width WIDTH_PX`
    *   Type: int
    *   Default: None
    *   Description: For 'grid' layout: target width in pixels for individual thumbnails (e.g., 320). Overrides automatic sizing. Cell height adjusts to maintain aspect ratio.
*   `--max_frames_for_print NUM_FRAMES`
    *   Type: int
    *   Default: None
    *   Description: For 'grid' layout: target maximum number of frames in the final print. If frame extraction yields more, frames will be sampled down to this count.
*   `--target_row_height HEIGHT_PX`
    *   Type: int
    *   Default: `100`
    *   Description: For 'timeline' layout: target height in pixels for each row.
*   `--output_image_width WIDTH_PX`
    *   Type: int
    *   Default: `1200`
    *   Description: For 'timeline' layout: target width in pixels for the final output image.

**Common Styling, File & Metadata Options**:

*   `--padding PADDING_PX`
    *   Type: int
    *   Default: `5`
    *   Description: Padding in pixels around and between thumbnails.
*   `--background_color HEX_COLOR`
    *   Type: string
    *   Default: `#FFFFFF` (white)
    *   Description: Background color for the MoviePrint image, in hex format.
*   `--frame_format {jpg,png}`
    *   Type: string
    *   Default: `jpg`
    *   Choices: `jpg`, `png`
    *   Description: Format for temporary extracted frame images.
*   `--temp_dir PATH`
    *   Type: string
    *   Default: None
    *   Description: Optional global directory for storing temporary frames. If specified, this directory will NOT be automatically cleaned up.
*   `--save_metadata_json`
    *   Action: store_true
    *   Description: If specified, save a JSON sidecar file with detailed metadata alongside the MoviePrint image.
*   `--detect_faces`
    *   Action: store_true
    *   Description: Enable face detection on thumbnails. This can be performance-intensive.
*   `--haar_cascade_xml XML_PATH`
    *   Type: string
    *   Default: None (uses OpenCV's default)
    *   Description: Path to a custom Haar Cascade XML file for face detection. If not provided, uses OpenCV's default frontal face cascade.
*   `--rotate_thumbnails DEGREES`
    *   Type: int
    *   Default: `0`
    *   Choices: `0`, `90`, `180`, `270`
    *   Description: Rotate all thumbnails clockwise by the specified degrees.
*   `--max_output_filesize_kb SIZE`
    *   Type: int
    *   Default: None
    *   Description: Attempt to reduce the final MoviePrint image so its file size does not exceed this value in kilobytes. This corresponds to the "Max Output Filesize (KB)" option in the GUI.

## GUI Settings Persistence

The GUI saves common settings (like last used input/output paths, extraction parameters, layout choices, etc.) to a file named `movieprint_gui_settings.json` in the same directory as the application. These settings are automatically loaded when the GUI starts.

## Known Issues / Limitations
None at this time.
## Future Enhancements / Roadmap
*   Ability for users to select/deselect specific thumbnails from the preview for inclusion/exclusion in the final print.
*   More advanced timeline layout options (e.g., variable row heights, grouping).
*   Integration of more sophisticated scene detection algorithms or options.

## Contributing
Contributions are welcome! Please fork the repository, make your changes on a separate branch, and submit a pull request with a clear description of your changes.

 
