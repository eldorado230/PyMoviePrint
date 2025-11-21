# Building PyMoviePrint for macOS

This guide explains how to package the PyMoviePrint GUI as a standalone macOS application (`.app`).

## Prerequisites

1.  **macOS**: You must be running this on a macOS machine.
2.  **Python 3.8+**: Ensure Python is installed.
3.  **Terminal**: You will need to run commands in the terminal.

## Quick Start

We have provided a script to automate the build process.

1.  Open Terminal.
2.  Navigate to the project directory.
3.  Run the build script:
    ```bash
    ./build_macos.sh
    ```

The script will:
*   Create a temporary virtual environment.
*   Install all necessary dependencies.
*   Install PyInstaller.
*   Build the `MoviePrint.app`.

Once finished, you will find the application in the `dist/` folder:
`dist/MoviePrint.app`

## Manual Build Instructions

If you prefer to run the steps manually:

1.  **Set up a virtual environment**:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    pip install pyinstaller
    ```

3.  **Run PyInstaller**:
    ```bash
    pyinstaller movieprint_gui.spec
    ```

4.  **Locate the App**:
    The application will be in the `dist/` folder.

## Troubleshooting

*   **"App is damaged and can't be opened"**: This is a common macOS security feature for unsigned apps. To fix this, you may need to remove the quarantine attribute:
    ```bash
    xattr -cr dist/MoviePrint.app
    ```
*   **Missing dependencies**: If the app crashes immediately, run it from the terminal to see error messages:
    ```bash
    dist/MoviePrint.app/Contents/MacOS/MoviePrint
    ```
