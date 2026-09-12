@echo off
echo ========================================
echo  PyMoviePrint Runner
echo ========================================
echo.
echo Changing to script directory...
cd /d "%~dp0"
echo Done.
echo.
echo Installing/Verifying dependencies from requirements.txt...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed. The GUI was not launched.
    pause
    exit /b 1
)
echo.
echo Launching PyMoviePrint GUI...
echo If the GUI does not start, please check for any error messages above.
echo.
python movieprint_gui.py

echo.
echo ========================================
echo  GUI closed. Press any key to exit.
echo ========================================
pause
