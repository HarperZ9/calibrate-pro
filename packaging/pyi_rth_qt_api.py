"""PyInstaller runtime hook selecting Calibrate Pro's sole Qt binding."""

import os

os.environ["QT_API"] = "pyside6"
