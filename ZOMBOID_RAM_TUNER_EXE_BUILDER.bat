@echo off
setlocal
 title Build Project Zomboid RAM Picker

rem Find the real Windows Desktop, including OneDrive redirection.
set "PZ_DESKTOP="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "PZ_DESKTOP=%%D"
if not defined PZ_DESKTOP set "PZ_DESKTOP=%USERPROFILE%\Desktop"
set "PZ_SOURCE=%PZ_DESKTOP%\ZOMBOID_RAM_PICKER.py"
set "PZ_VIDEO=%PZ_DESKTOP%\slow.mp4"
set "PZ_BUILD=%PZ_DESKTOP%\ZOMBOID_RAM_BUILD"

if not exist "%PZ_SOURCE%" (
    echo ERROR: Script not found:
    echo "%PZ_SOURCE%"
    goto :failed
)
if not exist "%PZ_VIDEO%" (
    echo ERROR: Video not found:
    echo "%PZ_VIDEO%"
    goto :failed
)

rem Prefer the Windows Python launcher; fall back to python on PATH.
set "PZ_PY=py -3"
%PZ_PY% -c "import sys" >nul 2>&1
if errorlevel 1 (
    set "PZ_PY=python"
)
%PZ_PY% -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3 is required to build this program.
    goto :failed
)

echo Installing build dependencies...
%PZ_PY% -m pip install --upgrade pyinstaller PySide6
if errorlevel 1 goto :failed

if not exist "%PZ_BUILD%" mkdir "%PZ_BUILD%"
if not exist "%PZ_BUILD%" goto :failed
pushd "%PZ_BUILD%"
if errorlevel 1 goto :failed

rem Generate an EXE icon matching the embedded PZ window icon.
%PZ_PY% -c "import os,sys; from PySide6.QtWidgets import QApplication; from PySide6.QtCore import Qt; from PySide6.QtGui import QPixmap,QPainter,QColor,QFont; app=QApplication([]); pix=QPixmap(256,256); pix.fill(QColor('#080c10')); p=QPainter(pix); p.fillRect(0,0,256,20,QColor('#385a75')); p.setPen(QColor('#b5ccde')); p.setFont(QFont('Segoe UI',100,QFont.Weight.Bold)); p.drawText(pix.rect(),Qt.AlignmentFlag.AlignCenter,'PZ'); p.end(); sys.exit(0 if pix.save('pz_ram.ico','ICO') else 1)"
if errorlevel 1 goto :build_failed

echo.
echo Building EXE with embedded video. This can take several minutes...
%PZ_PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name "ZOMBOID_RAM_PICKER" --icon "pz_ram.ico" --add-data "%PZ_VIDEO%;." --collect-all PySide6.QtMultimedia --collect-all PySide6.QtMultimediaWidgets --distpath "%PZ_BUILD%\dist" --workpath "%PZ_BUILD%\work" --specpath "%PZ_BUILD%" "%PZ_SOURCE%"
if errorlevel 1 goto :build_failed
if not exist "%PZ_BUILD%\dist\ZOMBOID_RAM_PICKER.exe" goto :build_failed
copy /y "%PZ_BUILD%\dist\ZOMBOID_RAM_PICKER.exe" "%PZ_DESKTOP%\ZOMBOID_RAM_PICKER.exe" >nul
if errorlevel 1 goto :build_failed
popd

echo.
echo SUCCESS! Standalone program created:
echo "%PZ_DESKTOP%\ZOMBOID_RAM_PICKER.exe"
echo.
echo Video is included. Other users do not need Python installed.
echo The embedded video extracts at startup, so the first launch may take a moment.
pause
exit /b 0

:build_failed
popd
:failed
echo.
echo BUILD FAILED. Read the error above.
pause
exit /b 1
