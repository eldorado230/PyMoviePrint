@echo off
cd /d "%~dp0"
pip install -r requirements.txt
python movieprint_gui.py
pause
