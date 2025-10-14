# PyMoviePrint User Guide

## Introduction

Welcome to the PyMoviePrint User Guide. This guide provides detailed instructions on how to use PyMoviePrint, a Python application for creating "movie prints" (contact sheets or thumbnail indexes) from your video files.

## Table of Contents

1.  [Features](#features)
2.  [Setup and Installation](#setup-and-installation)
3.  [Using the Graphical User Interface (GUI)](#using-the-graphical-user-interface-gui)
    *   [Running the GUI](#running-the-gui)
    *   [Main Window Overview](#main-window-overview)
    *   [Input/Output Section](#inputoutput-section)
    *   [Extraction & Segment Tab](#extraction--segment-tab)
    *   [Layout Tab](#layout-tab)
    *   [Thumbnail Preview Tab](#thumbnail-preview-tab)
    *   [Batch & Output Tab](#batch--output-tab)
    *   [Common & Advanced Tab](#common--advanced-tab)
    *   [Generating a MoviePrint](#generating-a-movieprint)
4.  [Using the Command-Line Interface (CLI)](#using-the-command-line-interface-cli)
    *   [Basic Usage](#basic-usage)
    *   [Command-Line Options](#command-line-options)
    *   [Examples](#examples)
5.  [Troubleshooting](#troubleshooting)
6.  [Contributing](#contributing)

## Features

PyMoviePrint offers a rich set of features for creating customized movie prints:

*   **Graphical User Interface (GUI)**: An intuitive interface for interactive operation.
*   **Command-Line Interface (CLI)**: For scripting, automation, and batch processing.
*   **Frame Extraction Modes**:
    *   **Interval Mode**: Extract frames at regular time or frame intervals.
    *   **Shot Detection Mode**: Use PySceneDetect to extract frames at detected shot boundaries.
*   **Time Segmentation**: Specify custom start and end times for processing videos.
*   **Frame/Shot Exclusion**: Exclude specific frames or shots from your movie print.
*   **Layout Modes**:
    *   **Grid Layout**: Arrange thumbnails in a standard grid.
    *   **Timeline Layout**: Arrange thumbnails proportionally to shot duration.
*   **Customization**: Adjust padding, background color, thumbnail rotation, and more.
*   **Batch Processing**: Process multiple video files or entire directories at once.
*   **Metadata**: Save detailed information about the generation process to a JSON file.
*   **And more**: Face detection, custom temporary directories, file size targeting, and persistent GUI settings.

## Setup and Installation

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
    ```bash
    pip install -r requirements.txt
    ```

## Using the Graphical User Interface (GUI)

### Running the GUI

To run the GUI, execute the following command in your terminal:
```bash
python movieprint_gui.py
```

### Main Window Overview

The main window is divided into several sections:
*   **Input/Output Section**: For selecting video files and the output directory.
*   **Tabs Section**: For configuring extraction, layout, and other settings.
*   **Action/Log Section**: For starting the generation process and viewing logs.

### Input/Output Section

*   **Video File(s) / Dir**: Select one or more video files, or a single directory containing videos. You can also drag and drop files or directories onto this field.
*   **Output Directory**: Choose the directory where the generated movie prints will be saved.

### Extraction & Segment Tab

*   **Extraction Mode**: Choose between `interval` and `shot` mode.
*   **Interval (seconds/frames)**: Set the time or frame interval for `interval` mode.
*   **Shot Threshold**: Adjust the sensitivity for `shot` mode.
*   **Start/End Time**: Specify a segment of the video to process.
*   **Exclude Frames/Shots**: List frame numbers or shot indices to exclude.

### Layout Tab

*   **Layout Mode**: Choose between `grid` and `timeline` layout.
*   **Max Frames for Print**: Set a target maximum number of frames for the movie print.
*   **Grid Options**: Configure the number of columns, rows, and thumbnail width for `grid` layout.
*   **Timeline Options**: Configure the row height and output image width for `timeline` layout.

### Thumbnail Preview Tab

*   **Preview Extracted Thumbnails**: Click this button to generate a preview of the thumbnails based on the current settings.

### Batch & Output Tab

*   **Output Filename**: Specify a filename for a single input file.
*   **Output Suffix**: Set a suffix for filenames in batch mode.
*   **Video Extensions**: Define the video file extensions to look for when scanning directories.
*   **Recursive Directory Scan**: Scan directories recursively for video files.

### Common & Advanced Tab

*   **Padding**: Set the padding around and between thumbnails.
*   **Background Color**: Choose a background color for the movie print.
*   **Frame Format**: Select the format for temporary extracted frames (jpg or png).
*   **Rotate Thumbnails**: Rotate all thumbnails by a specified angle.
*   **Custom Temp Directory**: Specify a directory for temporary frames.
*   **Haar Cascade XML**: Provide a custom Haar Cascade XML file for face detection.
*   **Save Metadata JSON**: Save a JSON file with detailed metadata.
*   **Detect Faces**: Enable face detection on thumbnails.
*   **Max Output Filesize (KB)**: Set a target maximum file size for the output image.
*   **Reset All Settings to Defaults**: Reset all settings to their default values.

### Generating a MoviePrint

Once you have configured all the settings, click the **Generate MoviePrint** button to start the process.

## Using the Command-Line Interface (CLI)

### Basic Usage

The basic structure of a CLI command is as follows:
```bash
python movieprint_maker.py <input_paths...> <output_dir> [options]
```

### Command-Line Options

For a full list of command-line options, please refer to the `README.md` file.

### Examples

*   **Simple grid (5 columns) for a single video, extracting every 10 seconds**:
    ```bash
    python movieprint_maker.py my_video.mp4 ./output --columns 5 --interval_seconds 10
    ```

*   **Timeline layout using shot detection, with a target row height of 120px**:
    ```bash
    python movieprint_maker.py movie.mov ./output --extraction_mode shot --layout_mode timeline --target_row_height 120
    ```

## Troubleshooting

*   **GUI does not start**: Ensure you have installed all the dependencies from `requirements.txt`.
*   **No frames extracted**: Check that the video file is not corrupted and that the start and end times are set correctly.

## Contributing

Contributions are welcome! Please fork the repository, make your changes on a separate branch, and submit a pull request.
