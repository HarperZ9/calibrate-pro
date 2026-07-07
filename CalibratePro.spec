# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['calibrate_pro.core', 'calibrate_pro.core.color_math', 'calibrate_pro.core.calibration_engine', 'calibrate_pro.core.lut_engine', 'calibrate_pro.gui', 'calibrate_pro.gui.app', 'calibrate_pro.hardware', 'calibrate_pro.sensorless', 'calibrate_pro.panels', 'calibrate_pro.panels.builtin_panels', 'calibrate_pro.panels.database', 'build_color', 'numpy', 'scipy']
hiddenimports += collect_submodules('calibrate_pro')


a = Analysis(
    ['calibrate_pro\\main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CalibratePro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
