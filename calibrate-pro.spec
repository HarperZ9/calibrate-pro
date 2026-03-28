# -*- mode: python ; coding: utf-8 -*-
# Calibrate Pro — PyInstaller build spec
# Targets <300MB by excluding ML frameworks and unused packages

a = Analysis(
    ['calibrate_pro/main.py'],
    pathex=[],
    binaries=[],
    datas=[('dwm_lut', 'dwm_lut')],
    hiddenimports=[
        'calibrate_pro.gui.theme',
        'calibrate_pro.gui.icons',
        'calibrate_pro.gui.workers',
        'calibrate_pro.gui.dialogs',
        'calibrate_pro.panels.panel_types',
        'calibrate_pro.panels.builtin_panels',
        'quanta_color',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # ML frameworks (4.5GB+ — not used by calibrate-pro)
        'torch', 'torchvision', 'torchaudio',
        'transformers', 'diffusers', 'accelerate', 'safetensors',
        'huggingface_hub', 'tokenizers',
        # Data science (not needed)
        'pandas', 'sklearn', 'scikit-learn',
        'matplotlib', 'PIL', 'Pillow',
        'sympy', 'colour',
        # Document processing
        'pymupdf', 'fitz', 'reportlab',
        # GUI frameworks we don't use
        'tkinter', '_tkinter', 'wx',
        # Testing
        'pytest', 'hypothesis', 'coverage',
        # Jupyter
        'IPython', 'jupyter', 'notebook',
        # Other
        'cv2', 'opencv', 'setuptools', 'pip', 'wheel',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='calibrate-pro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
)
