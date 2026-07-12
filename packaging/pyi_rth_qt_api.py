"""Select Calibrate Pro's sole Qt binding and Windows-native TLS backend."""

import os

os.environ["QT_API"] = "pyside6"
os.environ["QT_TLS_BACKEND"] = "schannel"
