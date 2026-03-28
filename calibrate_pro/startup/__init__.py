"""
Calibrate Pro Startup Module

Provides auto-load functionality for calibration LUTs on system startup.
"""

from .calibration_loader import (
    apply_saved_calibrations,
    run_service,
    start_service_command,
)
from .lut_autoload import (
    check_startup_enabled,
    create_startup_shortcut,
    load_calibration_luts,
    remove_startup,
)

__all__ = [
    'load_calibration_luts',
    'create_startup_shortcut',
    'remove_startup',
    'check_startup_enabled',
    'run_service',
    'apply_saved_calibrations',
    'start_service_command',
]
