"""Cross-platform import contract for the Windows profile boundary."""

from __future__ import annotations

import subprocess
import sys
import textwrap

from calibrate_pro.profiles import profile_installer


def test_profile_installer_imports_fail_closed_without_winreg() -> None:
    script = textwrap.dedent(
        f"""
        import builtins
        import runpy

        real_import = builtins.__import__
        def blocked_import(name, *args, **kwargs):
            if name == "winreg":
                raise ModuleNotFoundError("simulated non-Windows runtime")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = blocked_import
        namespace = runpy.run_path({str(profile_installer.__file__)!r}, run_name="profile_installer_no_winreg")
        assert namespace["winreg"] is None
        assert namespace["get_associated_profiles"](r"\\\\.\\DISPLAY1") == []
        """
    )
    completed = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True)

    assert completed.returncode == 0, completed.stderr
