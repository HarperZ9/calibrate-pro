@echo off
echo === Building Calibrate Pro Installer ===
echo.

REM Ensure we're using the right Python
set PYTHON=C:\Users\Zain\AppData\Local\Programs\Python\Python313\python.exe

REM Install PyInstaller if needed
%PYTHON% -m pip install pyinstaller --quiet

REM Build the executable
%PYTHON% -m PyInstaller ^
    --name "CalibratePro" ^
    --onefile ^
    --windowed ^
    --hidden-import "calibrate_pro.core" ^
    --hidden-import "calibrate_pro.core.color_math" ^
    --hidden-import "calibrate_pro.core.calibration_engine" ^
    --hidden-import "calibrate_pro.core.lut_engine" ^
    --hidden-import "calibrate_pro.gui" ^
    --hidden-import "calibrate_pro.gui.app" ^
    --hidden-import "calibrate_pro.hardware" ^
    --hidden-import "calibrate_pro.sensorless" ^
    --hidden-import "calibrate_pro.panels" ^
    --hidden-import "calibrate_pro.panels.builtin_panels" ^
    --hidden-import "calibrate_pro.panels.database" ^
    --hidden-import "quanta_color" ^
    --hidden-import "numpy" ^
    --hidden-import "scipy" ^
    --collect-submodules "calibrate_pro" ^
    calibrate_pro\main.py

echo.
if exist dist\CalibrateProSetup.exe (
    echo === BUILD SUCCESS ===
    echo Output: dist\CalibrateProSetup.exe
    for %%A in (dist\CalibrateProSetup.exe) do echo Size: %%~zA bytes
) else (
    echo === BUILD FAILED ===
)
