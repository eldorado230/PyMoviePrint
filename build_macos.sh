#!/bin/bash

# Check if python3 is available
if ! command -v python3 &> /dev/null
then
    echo "python3 could not be found. Please install Python 3.8 or newer."
    exit 1
fi

echo "Creating virtual environment..."
python3 -m venv .venv_build
source .venv_build/bin/activate

echo "Installing dependencies..."
pip install -r requirements.txt
pip install pyinstaller

echo "Building macOS app..."
# Clean previous builds
rm -rf build dist

# Run PyInstaller
pyinstaller movieprint_gui.spec

if [ -d "dist/MoviePrint.app" ]; then
    echo "------------------------------------------------"
    echo "Build successful!"
    echo "The application is located at: dist/MoviePrint.app"
    echo "You can drag this to your Applications folder."
    echo "------------------------------------------------"
else
    echo "Build failed. Please check the output above."
fi

deactivate
