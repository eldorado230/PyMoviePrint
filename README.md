WIP
feat: Add Python MoviePrint tool with CLI and GUI
This commit introduces a new Python-based application, "MoviePrint,"
designed to generate visual summaries (contact sheets) of videos.
The tool is a Python-only remake inspired by the functionality of
MoviePrint v004.

Key Features Implemented:
- Core: Video loading, frame extraction (interval-based), thumbnail
  grid generation, and image saving.
- Advanced Extraction: Shot-based frame extraction using PySceneDetect.
- Layouts:
    - Standard grid layout with configurable columns and padding.
    - Timeline view where thumbnail widths represent shot durations.
- Batch Processing: Process multiple video files or entire directories.
- Metadata: Save detailed metadata (video info, generation parameters,
  thumbnail details, face detection results) as a JSON sidecar file.
- Time Segmentation: Define in/out points to process specific video segments.
- Thumbnail Management: Exclude specific frames or shots from the output.
- Face Detection: Optionally run face detection on thumbnails and save
  results (number of faces, bounding boxes) in metadata.
- Transformations: Rotate thumbnails by 90, 180, or 270 degrees.

Interfaces:
1.  Command-Line Interface (CLI):
    - All features are accessible via `movieprint_maker.py`.
    - Comprehensive command-line arguments for customization.
    - Detailed logging and progress feedback.
2.  Graphical User Interface (GUI):
    - Developed using Tkinter (`movieprint_gui.py`).
    - Exposes most CLI functionalities in a user-friendly way.
    - Tabbed interface for organized settings.
    - File and directory dialogs for easy input/output selection.
    - Threaded backend processing to keep the GUI responsive.
    - Progress bar and log area for feedback.
    - Tooltips for all options.

The project structure includes:
- `movieprint_maker.py`: Main CLI script and core logic orchestration.
- `video_processing.py`: Handles video loading, frame/shot extraction.
- `image_grid.py`: Manages thumbnail grid and timeline layout generation.
- `movieprint_gui.py`: Tkinter-based GUI application.

This provides a powerful and flexible tool for creating visual
summaries of video content, suitable for both command-line automation
and interactive use.
